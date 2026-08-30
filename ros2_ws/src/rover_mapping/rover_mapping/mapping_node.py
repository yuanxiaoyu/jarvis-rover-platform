"""ROS 2 session manager for the rover's asynchronous mapping backend."""

from __future__ import annotations

import math
import re
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from geometry_msgs.msg import Twist
from nav_msgs.msg import OccupancyGrid
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import Imu, LaserScan
from std_msgs.msg import Bool
from tf2_ros import Buffer, TransformListener

from rover_interfaces.msg import MappingSession
from rover_interfaces.srv import MappingCommand

from .map_validation import Pose2D, validate_pose_in_map
from .persistence import SessionStore
from .preflight import (
    CheckResult,
    PreflightChecker,
    PreflightReport,
    PreflightSnapshot,
)
from .session import CommandType, MappingState, SessionController
from .slam_gateway import RosSlamGateway, SlamGateway


_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class MappingNode(Node):
    """Own the mapping session lifecycle while keeping callbacks non-blocking."""

    def __init__(
        self,
        *,
        gateway: SlamGateway | None = None,
        store: SessionStore | None = None,
    ) -> None:
        super().__init__("rover_mapping")
        self._declare_parameters()
        self._lock = threading.RLock()
        self._controller = SessionController("default")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mapping")
        self._active_future: Future[Any] | None = None
        self._last_error_reported = ""
        self._last_received: dict[str, float] = {}
        self._last_map_received: float | None = None
        self._latest_map: OccupancyGrid | None = None
        self._map_session_id: str | None = None
        self._emergency_stop = False

        self._session_dir = Path(str(self.get_parameter("session_dir").value))
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._store = store or SessionStore(self._session_dir)
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        status_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )

        scan_topic = str(self.get_parameter("scan_topic").value)
        odom_topic = str(self.get_parameter("odom_raw_topic").value)
        imu_topic = str(self.get_parameter("imu_topic").value)
        map_topic = str(self.get_parameter("map_topic").value)
        self._scan_sub = self.create_subscription(LaserScan, scan_topic, self._scan_callback, self._qos)
        self._odom_sub = self.create_subscription(AnyOdometry, odom_topic, self._odom_callback, self._qos)
        self._imu_sub = self.create_subscription(Imu, imu_topic, self._imu_callback, self._qos)
        self._map_sub = self.create_subscription(OccupancyGrid, map_topic, self._map_callback, self._qos)
        self._estop_sub = self.create_subscription(
            Bool,
            str(self.get_parameter("emergency_stop_topic").value),
            self._emergency_stop_callback,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE),
        )

        self._status_pub = self.create_publisher(MappingSession, "/mapping/status", status_qos)
        self._motion_pub = self.create_publisher(Bool, "/mapping/motion_allowed", status_qos)
        self._diagnostics_pub = self.create_publisher(DiagnosticArray, "/mapping/diagnostics", status_qos)
        self._stop_pub = self.create_publisher(
            Twist,
            str(self.get_parameter("stop_topic").value),
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE),
        )
        self._command_srv = self.create_service(MappingCommand, "/mapping/command", self._command_callback)
        status_hz = float(self.get_parameter("status_publish_hz").value)
        if status_hz <= 0:
            raise ValueError("status_publish_hz must be positive")
        self._status_timer = self.create_timer(1.0 / status_hz, self._publish_status)

        self._gateway = gateway if gateway is not None else self._create_gateway()
        self._preflight_checker = PreflightChecker(
            float(self.get_parameter("sensor_timeout_seconds").value),
            int(self.get_parameter("min_free_bytes").value),
            required_topics=(scan_topic, odom_topic, imu_topic),
            required_tf=(
                f"{self.get_parameter('base_frame').value}->"
                f"{self.get_parameter('laser_frame').value}"
            ),
        )
        self._initial_pause_done = threading.Event()
        self._initial_pause_ok = False
        self._initial_pause_thread = threading.Thread(
            target=self._initial_pause,
            name="mapping-initial-pause",
            daemon=True,
        )
        self._initial_pause_thread.start()
        self.get_logger().info("rover_mapping ready; motion remains locked until a mapping session starts")

    def _declare_parameters(self) -> None:
        defaults = {
            "scan_topic": "/scan",
            "odom_raw_topic": "/odom_raw",
            "imu_topic": "/imu",
            "map_topic": "/map",
            "session_dir": "/workspace/data/maps",
            "base_frame": "base_footprint",
            "laser_frame": "laser_frame",
            "odom_frame": "odom",
            "map_frame": "map",
            "sensor_timeout_seconds": 0.75,
            "min_free_bytes": 104857600,
            "status_publish_hz": 2.0,
            "checkpoint_on_pause": True,
            "slam_service_prefix": "/slam_toolbox",
            "stop_topic": "/mapping/stop_cmd_vel",
            "emergency_stop_topic": "/emergency_stop",
            "slam_service_timeout_seconds": 10.0,
            "pause_service_suffix": "pause_new_measurements",
            "clear_queue_service_suffix": "clear_queue",
            "save_map_service_suffix": "save_map",
            "serialize_service_suffix": "serialize_map",
            "deserialize_service_suffix": "deserialize_map",
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

    def _create_gateway(self) -> SlamGateway | None:
        suffixes = {
            "pause": str(self.get_parameter("pause_service_suffix").value),
            "clear_queue": str(self.get_parameter("clear_queue_service_suffix").value),
            "save_map": str(self.get_parameter("save_map_service_suffix").value),
            "serialize_pose_graph": str(self.get_parameter("serialize_service_suffix").value),
            "deserialize_pose_graph": str(self.get_parameter("deserialize_service_suffix").value),
        }
        try:
            return RosSlamGateway(
                self,
                prefix=str(self.get_parameter("slam_service_prefix").value),
                timeout_s=float(self.get_parameter("slam_service_timeout_seconds").value),
                service_suffixes=suffixes,
            )
        except (RuntimeError, ValueError) as exc:
            self.get_logger().error(f"unable to create SLAM gateway: {exc}")
            return None

    def _scan_callback(self, _message: LaserScan) -> None:
        self._last_received[str(self.get_parameter("scan_topic").value)] = time.monotonic()

    def _odom_callback(self, _message: Any) -> None:
        self._last_received[str(self.get_parameter("odom_raw_topic").value)] = time.monotonic()

    def _imu_callback(self, _message: Imu) -> None:
        self._last_received[str(self.get_parameter("imu_topic").value)] = time.monotonic()

    def _map_callback(self, message: OccupancyGrid) -> None:
        with self._lock:
            self._latest_map = message
            self._map_session_id = self._controller.snapshot().session_id
            self._last_map_received = time.monotonic()

    def _emergency_stop_callback(self, message: Bool) -> None:
        with self._lock:
            self._emergency_stop = bool(message.data)
            if self._emergency_stop:
                self._publish_zero()

    def _command_callback(self, request: MappingCommand.Request, response: MappingCommand.Response) -> MappingCommand.Response:
        try:
            command = CommandType(int(request.command))
        except (TypeError, ValueError):
            return self._reject_response(response, "unknown mapping command")

        with self._lock:
            if self._active_future is not None and not self._active_future.done():
                return self._reject_response(response, "another mapping command is still running")
            current = self._controller.snapshot()
            requested_session = str(request.session_id).strip()
            if command in (CommandType.START, CommandType.LOAD):
                if not _COMPONENT_RE.fullmatch(requested_session):
                    return self._reject_response(response, "session_id is invalid")
                if command is CommandType.LOAD and int(request.match_type) not in (2, 3):
                    return self._reject_response(response, "match_type must be 2 or 3")
                if command is CommandType.LOAD and not _COMPONENT_RE.fullmatch(
                    str(request.map_name).strip() or "map"
                ):
                    return self._reject_response(response, "map_name is invalid")
                if command is CommandType.START and not _COMPONENT_RE.fullmatch(
                    str(request.map_name).strip() or "map"
                ):
                    return self._reject_response(response, "map_name is invalid")
                if command is CommandType.START and current.state is MappingState.ERROR_RECOVERABLE and requested_session != current.session_id:
                    return self._reject_response(
                        response,
                        "restart the mapping runtime before starting a new session",
                    )
                if command is CommandType.START and (
                    current.state is MappingState.IDLE
                    and current.current_revision is not None
                    and requested_session != current.session_id
                ):
                    return self._reject_response(
                        response,
                        "restart the mapping runtime before starting a new session",
                    )
                if current.state is MappingState.IDLE and requested_session != current.session_id:
                    self._controller = SessionController(requested_session)
                    self._latest_map = None
                    self._last_map_received = None
                    self._map_session_id = None
                    current = self._controller.snapshot()
            elif requested_session and requested_session != current.session_id:
                return self._reject_response(response, "session_id does not match active session")

            previous_state = current.state
            result = self._controller.request(
                command,
                preflight_ok=True if command in (CommandType.START, CommandType.RESUME) else None,
                has_initial_pose=bool(request.has_initial_pose),
            )
            if not result.accepted:
                return self._reject_response(response, result.message)
            if command is CommandType.START:
                self._latest_map = None
                self._last_map_received = None
                self._map_session_id = None
            self._publish_status()
            self._active_future = self._executor.submit(
                self._run_command,
                request,
                command,
                previous_state,
            )
            self._active_future.add_done_callback(self._worker_finished)
            snapshot = self._controller.snapshot()
            response.accepted = True
            response.state = int(snapshot.state)
            response.message = result.message
            return response

    def _reject_response(self, response: MappingCommand.Response, message: str) -> MappingCommand.Response:
        with self._lock:
            response.accepted = False
            response.state = int(self._controller.snapshot().state)
        response.message = message
        return response

    def _run_command(self, request: MappingCommand.Request, command: CommandType, previous_state: MappingState) -> None:
        try:
            if command is CommandType.START:
                self._run_start()
            elif command is CommandType.PAUSE:
                self._run_pause()
            elif command is CommandType.RESUME:
                self._run_resume()
            elif command is CommandType.SAVE:
                self._run_save(request, previous_state)
            elif command is CommandType.STOP:
                self._run_stop(request)
            elif command is CommandType.LOAD:
                self._run_load(request)
        except Exception as exc:
            self._fail(str(exc))

    def _initial_pause(self) -> None:
        try:
            if self._gateway is not None and self._gateway.pause(True):
                self._initial_pause_ok = True
            elif self._gateway is not None:
                self.get_logger().warning(
                    "SLAM initial pause was not acknowledged; motion remains locked"
                )
        finally:
            self._initial_pause_done.set()

    def _run_start(self) -> None:
        self._publish_zero()
        if not self._initial_pause_done.wait(
            timeout=float(self.get_parameter("slam_service_timeout_seconds").value)
        ) or not self._initial_pause_ok:
            self._fail("SLAM initial pause did not complete")
            return
        report = self._run_preflight(require_map_tf=False)
        if not report.ok:
            self._fail(_report_message(report))
            return
        if self._gateway is None or not self._gateway.services_ready():
            self._fail("SLAM services are not ready")
            return
        if not self._gateway.pause(False):
            self._fail("SLAM refused to resume measurements")
            return
        with self._lock:
            self._controller.mark_started()

    def _run_pause(self) -> None:
        self._publish_zero()
        if self._gateway is None or not self._gateway.pause(True):
            self._fail("SLAM refused to pause measurements")
            return
        if not self._gateway.clear_queue():
            self._fail("SLAM queue could not be cleared")
            return
        if bool(self.get_parameter("checkpoint_on_pause").value):
            with self._lock:
                session_id = self._controller.snapshot().session_id
            if not self._save_revision(session_id, "checkpoint"):
                self._fail("pause checkpoint could not be saved")
                return
        with self._lock:
            self._controller.mark_paused()

    def _run_resume(self) -> None:
        self._publish_zero()
        report = self._run_preflight(require_map_tf=True)
        if not report.ok:
            self._fail(_report_message(report))
            return
        if self._gateway is None or not self._gateway.clear_queue():
            self._fail("SLAM queue could not be cleared")
            return
        if not self._gateway.pause(False):
            self._fail("SLAM refused to resume measurements")
            return
        with self._lock:
            self._controller.mark_resumed()

    def _run_save(self, request: MappingCommand.Request, previous_state: MappingState) -> None:
        self._publish_zero()
        with self._lock:
            session_id = self._controller.snapshot().session_id
        map_name = str(request.map_name).strip() or "map"
        revision = self._save_revision(session_id, map_name)
        if not revision:
            self._fail("mapping revision could not be saved")
            return
        with self._lock:
            if previous_state is MappingState.MAPPING:
                self._controller.mark_saved(resume=True, revision=revision)
            else:
                self._controller.mark_saved(resume=False, revision=revision)
                self._controller.mark_paused()

    def _run_stop(self, request: MappingCommand.Request) -> None:
        self._publish_zero()
        if self._gateway is None or not self._gateway.pause(True):
            self._fail("SLAM refused to stop measurements")
            return
        with self._lock:
            session_id = self._controller.snapshot().session_id
        map_name = str(request.map_name).strip() or "map"
        revision = self._save_revision(session_id, map_name)
        if not revision:
            self._fail("final mapping revision could not be saved")
            return
        with self._lock:
            self._controller.mark_saved(revision=revision)

    def _run_load(self, request: MappingCommand.Request) -> None:
        self._publish_zero()
        if not self._initial_pause_done.wait(
            timeout=float(self.get_parameter("slam_service_timeout_seconds").value)
        ) or not self._initial_pause_ok:
            self._fail("SLAM initial pause did not complete")
            return
        if self._gateway is None or not self._gateway.pause(True):
            self._fail("SLAM must be paused before loading a session")
            return
        if not self._gateway.clear_queue():
            self._fail("SLAM queue could not be cleared before loading")
            return
        with self._lock:
            session_id = self._controller.snapshot().session_id
        manifest = self._store.load_current(session_id)
        requested_map_name = str(request.map_name).strip() or "map"
        if manifest.get("map_name") != requested_map_name:
            self._fail("requested map does not match the current session")
            return
        paths = self._store.resolve_current_paths(session_id)
        pose = Pose2D(
            float(request.initial_pose.x),
            float(request.initial_pose.y),
            float(request.initial_pose.theta),
        )
        if not validate_pose_in_map(
            paths.map_yaml.read_text(encoding="utf-8"),
            paths.map_pgm.read_bytes(),
            pose,
        ):
            self._fail("initial pose is not on known free map space")
            return
        if self._gateway is None:
            self._fail("SLAM services are not ready")
            return
        with tempfile.TemporaryDirectory(prefix="rover-posegraph-") as temp_dir:
            graph_prefix = Path(temp_dir) / "graph"
            graph_prefix.with_suffix(".posegraph").write_bytes(paths.posegraph.read_bytes())
            if paths.posegraph_data.is_file():
                graph_prefix.with_suffix(".data").write_bytes(paths.posegraph_data.read_bytes())
            if not self._gateway.deserialize_pose_graph(
                str(graph_prefix), int(request.match_type or 2), pose
            ):
                self._fail("SLAM refused to deserialize pose graph")
                return
        with self._lock:
            self._controller.mark_paused()
            self._controller.mark_saved(
                resume=False,
                revision=str(manifest["revision_id"]),
            )
            self._controller.mark_paused()

    def _save_revision(self, session_id: str, map_name: str) -> str | None:
        if self._gateway is None:
            return None
        staging = self._session_dir / ".staging" / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=False)
        prefix = staging / "map"
        graph_path = staging / "posegraph"
        try:
            if not self._gateway.serialize_pose_graph(str(graph_path)):
                return None
            if not self._gateway.save_map(str(prefix)):
                return None
            pgm_path = _first_existing(prefix.with_suffix(".pgm"), prefix.with_suffix(".PGM"))
            yaml_path = _first_existing(prefix.with_suffix(".yaml"), prefix.with_suffix(".yml"))
            graph_output = _first_existing(
                graph_path,
                graph_path.with_suffix(".posegraph"),
            )
            graph_data_output = _first_existing(
                graph_path.with_suffix(".data"),
                graph_path.with_suffix(".posegraph.data"),
            )
            map_data: bytes
            map_yaml: str
            if pgm_path is not None and yaml_path is not None:
                map_data = pgm_path.read_bytes()
                map_yaml = yaml_path.read_text(encoding="utf-8")
            else:
                map_data, map_yaml = self._latest_map_files()
            if graph_output is None:
                return None
            revision = self._store.save_revision(
                session_id=session_id,
                map_name=map_name,
                map_pgm=map_data,
                map_yaml=map_yaml,
                pose_graph=graph_output.read_bytes(),
                posegraph_data=(
                    graph_data_output.read_bytes()
                    if graph_data_output is not None
                    else None
                ),
                metadata={
                    "map_frame": str(self.get_parameter("map_frame").value),
                    "odom_frame": str(self.get_parameter("odom_frame").value),
                    "base_frame": str(self.get_parameter("base_frame").value),
                    "map_topic": str(self.get_parameter("map_topic").value),
                },
            )
            return revision
        except (OSError, ValueError, TypeError) as exc:
            self.get_logger().error(f"mapping revision save failed: {exc}")
            return None
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _latest_map_files(self) -> tuple[bytes, str]:
        if self._map_session_id is None:
            raise ValueError("occupancy grid is not associated with a mapping session")
        with self._lock:
            session_id = self._controller.snapshot().session_id
        if self._map_session_id != session_id:
            raise ValueError("occupancy grid belongs to a different mapping session")
        message = self._latest_map
        if message is None or message.info.width <= 0 or message.info.height <= 0:
            raise ValueError("no occupancy grid is available")
        width = int(message.info.width)
        height = int(message.info.height)
        if len(message.data) != width * height:
            raise ValueError("occupancy grid dimensions do not match data")
        rows: list[bytes] = []
        for y in range(height - 1, -1, -1):
            pixels = bytearray()
            for value in message.data[y * width : (y + 1) * width]:
                if value < 0:
                    pixels.append(205)
                else:
                    pixels.append(max(0, min(255, 255 - round(value * 255 / 100))))
            rows.append(bytes(pixels))
        pgm = f"P5\n{width} {height}\n255\n".encode("ascii") + b"".join(rows)
        origin = message.info.origin.position
        yaw = _yaw_from_quaternion(message.info.origin.orientation)
        map_yaml = (
            "image: map.pgm\n"
            f"resolution: {float(message.info.resolution):.9g}\n"
            f"origin: [{float(origin.x):.9g}, {float(origin.y):.9g}, {yaw:.9g}]\n"
            "occupied_thresh: 0.65\n"
            "free_thresh: 0.196\n"
            "negate: 0\n"
        )
        return pgm, map_yaml

    def _run_preflight(self, *, require_map_tf: bool) -> PreflightReport:
        snapshot = self._preflight_snapshot()
        report = self._preflight_checker.check(snapshot)
        base_frame = str(self.get_parameter("base_frame").value)
        map_frame = str(self.get_parameter("map_frame").value)
        odom_frame = str(self.get_parameter("odom_frame").value)
        laser_frame = str(self.get_parameter("laser_frame").value)
        required_pairs = (
            f"{map_frame}->{odom_frame}",
            f"{odom_frame}->{base_frame}",
            f"{base_frame}->{laser_frame}",
        ) if require_map_tf else (
            f"{odom_frame}->{base_frame}",
            f"{base_frame}->{laser_frame}",
        )
        complete_tf = all(snapshot.tf_available.get(pair, False) for pair in required_pairs)
        if not complete_tf:
            checks = dict(report.checks)
            checks["complete TF chain"] = CheckResult(
                False,
                "required mapping TF chain is incomplete",
            )
            report = PreflightReport(ok=False, checks=checks)
        self._publish_diagnostics(report)
        return report

    def _preflight_snapshot(self) -> PreflightSnapshot:
        topics = (
            str(self.get_parameter("scan_topic").value),
            str(self.get_parameter("odom_raw_topic").value),
            str(self.get_parameter("imu_topic").value),
        )
        map_frame = str(self.get_parameter("map_frame").value)
        odom_frame = str(self.get_parameter("odom_frame").value)
        base_frame = str(self.get_parameter("base_frame").value)
        laser_frame = str(self.get_parameter("laser_frame").value)
        publisher_counts = {
            topic: len(self.get_publishers_info_by_topic(topic)) for topic in topics
        }
        now = time.monotonic()
        ages = {topic: now - self._last_received.get(topic, float("-inf")) for topic in topics}
        names = [name.lower() for name, _namespace in self.get_node_names_and_namespaces()]
        ekf_count = sum("ekf" in name for name in names)
        slam_nodes = [
            name
            for name in names
            if any(token in name for token in ("slam_toolbox", "cartographer", "gmapping"))
        ]
        allowed_slam_nodes = sum("async_slam_toolbox_node" in name for name in slam_nodes)
        competing_slam_nodes = max(
            0,
            len(slam_nodes) - allowed_slam_nodes,
            1 if allowed_slam_nodes != 1 else 0,
        )
        static_count = sum("static_transform_publisher" in name for name in names)
        # The three configured static transforms are expected; any additional
        # static publisher is a competing TF authority. Endpoint counts are
        # conservative because one node can publish several static transforms.
        tf_static_publishers = len(self.get_publishers_info_by_topic("/tf_static"))
        duplicate_tf_publishers = max(
            0,
            static_count - 3,
            tf_static_publishers - 3,
        )
        free_bytes = 0
        try:
            free_bytes = shutil.disk_usage(self._session_dir).free
        except OSError:
            pass
        required_tf = self._preflight_checker.required_tf
        return PreflightSnapshot(
            publisher_counts=publisher_counts,
            stream_age_s=ages,
            tf_available={
                f"{map_frame}->{odom_frame}": self._can_transform(
                    map_frame,
                    odom_frame,
                ),
                f"{odom_frame}->{base_frame}": self._can_transform(
                    odom_frame,
                    base_frame,
                ),
                required_tf: self._can_transform(
                    base_frame,
                    laser_frame,
                ),
                "base_link->imu_frame": self._can_transform(
                    "base_link",
                    "imu_frame",
                ),
            },
            duplicate_tf_publishers=duplicate_tf_publishers,
            duplicate_ekf_nodes=1 if ekf_count != 1 else 0,
            slam_backend_nodes=competing_slam_nodes,
            final_cmd_vel_publishers=len(self.get_publishers_info_by_topic("/cmd_vel")),
            teleop_cmd_vel_publishers=len(self.get_publishers_info_by_topic("/cmd_vel_teleop")),
            free_bytes=free_bytes,
            emergency_stop=self._emergency_stop,
        )

    def _can_transform(self, target: str, source: str) -> bool:
        try:
            return bool(
                self._tf_buffer.can_transform(
                    target,
                    source,
                    Time(),
                    timeout=Duration(seconds=0.20),
                )
            )
        except (RuntimeError, TypeError):
            return False

    def _publish_status(self) -> None:
        self._check_active_runtime_health()
        with self._lock:
            snapshot = self._controller.snapshot()
        message = MappingSession()
        message.header.stamp = self.get_clock().now().to_msg()
        message.session_id = snapshot.session_id
        message.state = int(snapshot.state)
        message.ready = snapshot.ready
        message.motion_allowed = snapshot.motion_allowed and not self._emergency_stop
        message.map_update_age_s = self._map_age()
        message.current_revision = snapshot.current_revision or ""
        message.last_error = snapshot.last_error
        self._status_pub.publish(message)
        allowed = Bool()
        allowed.data = bool(message.motion_allowed)
        self._motion_pub.publish(allowed)

    def _check_active_runtime_health(self) -> None:
        with self._lock:
            if self._controller.snapshot().state is not MappingState.MAPPING:
                return
        names = [name.lower() for name, _namespace in self.get_node_names_and_namespaces()]
        if not any("ekf_node" in name for name in names):
            self._fail("EKF node disappeared while mapping")
            return
        if not any("async_slam_toolbox_node" in name for name in names):
            self._fail("SLAM Toolbox node disappeared while mapping")

    def _map_age(self) -> float:
        if self._last_map_received is None:
            return -1.0
        return max(0.0, time.monotonic() - self._last_map_received)

    def _publish_diagnostics(self, report: PreflightReport) -> None:
        message = DiagnosticArray()
        message.header.stamp = self.get_clock().now().to_msg()
        status = DiagnosticStatus()
        status.name = "rover_mapping/preflight"
        status.level = DiagnosticStatus.OK if report.ok else DiagnosticStatus.ERROR
        status.message = "preflight passed" if report.ok else _report_message(report)
        status.values = [
            KeyValue(key=name, value=check.detail)
            for name, check in report.checks.items()
            if not check.ok
        ]
        message.status = [status]
        self._diagnostics_pub.publish(message)

    def _fail(self, message: str) -> None:
        with self._lock:
            self._controller.mark_failed(message)
        if message != self._last_error_reported:
            self.get_logger().error(message)
            self._last_error_reported = message
        self._publish_diagnostics(
            PreflightReport(
                ok=False,
                checks={"mapping command": _failed_check(message)},
            )
        )
        self._publish_zero()

    def _publish_zero(self) -> None:
        self._stop_pub.publish(Twist())

    def _worker_finished(self, future: Future[Any]) -> None:
        with self._lock:
            if self._active_future is future:
                self._active_future = None
        try:
            future.result()
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            self._fail(f"mapping worker failed: {exc}")

    def destroy_node(self) -> bool:
        self._publish_zero()
        if self._initial_pause_thread.is_alive():
            self._initial_pause_done.wait(timeout=1.0)
        self._executor.shutdown(wait=False, cancel_futures=True)
        return super().destroy_node()


def _first_existing(*paths: Path) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def _report_message(report: PreflightReport) -> str:
    failures = [f"{name}: {result.detail}" for name, result in report.checks.items() if not result.ok]
    return "; ".join(failures) or "mapping preflight failed"


def _failed_check(message: str) -> Any:
    from .preflight import CheckResult

    return CheckResult(False, message)


def _yaw_from_quaternion(quaternion: Any) -> float:
    return math.atan2(
        2.0 * (quaternion.w * quaternion.z + quaternion.x * quaternion.y),
        1.0 - 2.0 * (quaternion.y * quaternion.y + quaternion.z * quaternion.z),
    )


# Imported lazily by rclpy's type support at runtime; keeping the alias here
# makes the subscription annotation readable without another package import.
try:
    from nav_msgs.msg import Odometry as AnyOdometry
except ImportError:  # pragma: no cover - only reached outside ROS 2
    AnyOdometry = object  # type: ignore[misc,assignment]


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MappingNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
