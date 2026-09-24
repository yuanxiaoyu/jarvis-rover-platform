from __future__ import annotations

import math
import copy
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.hardware import GimbalState, RadarPoint, RadarScan
from app.models.map import Coordinate2D, GridOrigin, MapModel, MapSource, OccupancyGridMeta
from app.models.mapping import MappingCommandResult, MappingState, MappingStatus
from app.models.mission import MissionMode, MissionState
from app.models.sensor import BatteryReading, ImuReading, LidarReading, SensorSnapshot, TemperatureReading
from app.models.system import RobotPoseState
from app.models.zone import Zone
from app.services.navigation_map import overlay_restricted_zones, slow_zone_scale_at


class RosRuntimeStore:
    """Optional rclpy adapter. It fails closed when ROS is not installed or topics are absent."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        stale_seconds: float = 3.0,
        mapping_session_dir: str = "/workspace/data/maps",
        mapping_launch_command: list[str] | None = None,
    ) -> None:
        self.enabled = enabled
        self.stale_seconds = stale_seconds
        self.mapping_session_dir = Path(mapping_session_dir)
        self.mapping_launch_command = mapping_launch_command or ["ros2", "launch", "rover_bringup", "mapping.launch.py"]
        self._lock = threading.Lock()
        self._node: Any = None
        self._executor: Any = None
        self._thread: threading.Thread | None = None
        self._error: str | None = None
        self._closed = False
        self._scan: dict[str, Any] | None = None
        self._odom: dict[str, Any] | None = None
        self._imu: dict[str, Any] | None = None
        self._battery: dict[str, Any] | None = None
        self._map: dict[str, Any] | None = None
        self._gimbal = {"pan_deg": None, "tilt_deg": None, "updated": 0.0}
        self._pan_pub: Any = None
        self._tilt_pub: Any = None
        self._tf_buffer: Any = None
        self._tf_listener: Any = None
        self._mapping_process: subprocess.Popen[bytes] | None = None
        self._mapping_state = MappingState.IDLE
        self._mapping_session_id: str | None = None
        self._mapping_error = ""
        self._mapping_revision: str | None = None
        self._mapping_navigation_enabled = False
        self._exploration_lock = threading.RLock()
        self._exploration_status: dict[str, Any] = {
            "state": "idle",
            "message": "待命",
            "current_target": None,
            "completed_frontiers": 0,
            "failed_frontiers": 0,
            "remaining_frontiers": 0,
            "updated_at": time.time(),
        }
        self._exploration_clients: dict[str, Any] = {}
        self._emergency_stop_pub: Any = None
        self._navigation_map_pub: Any = None
        self._speed_scale_pub: Any = None
        self._map_message: Any = None
        self._zones: list[Zone] = []

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> None:
        if not self.enabled:
            self._error = "ROS bridge 未启用"
            return
        try:
            import rclpy
            from nav_msgs.msg import Odometry, OccupancyGrid
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
            from rclpy.time import Time
            from sensor_msgs.msg import Imu, LaserScan
            from std_msgs.msg import Bool, Float32, Int32, String, UInt16
            from std_srvs.srv import Trigger
            from tf2_ros import Buffer, TransformListener
        except Exception as exc:  # pragma: no cover - depends on ROS runtime image
            self._error = f"ROS 运行时不可用: {exc}"
            return

        try:
            rclpy.init(args=None)
            node = rclpy.create_node("rover_api_runtime")
            self._node = node
            self._executor = MultiThreadedExecutor(num_threads=2)
            self._executor.add_node(node)
            node.create_subscription(LaserScan, "/scan", self._on_scan, 10)
            node.create_subscription(Odometry, "/odom_raw", self._on_odom, 10)
            node.create_subscription(Odometry, "/odom", self._on_odom, 10)
            node.create_subscription(Imu, "/imu", self._on_imu, 10)
            node.create_subscription(UInt16, "/battery", self._on_battery, 10)
            node.create_subscription(OccupancyGrid, "/map", self._on_map, 1)
            self._pan_pub = node.create_publisher(Int32, "/servo_s1", 10)
            self._tilt_pub = node.create_publisher(Int32, "/servo_s2", 10)
            self._emergency_stop_pub = node.create_publisher(Bool, "/rover_navigation/emergency_stop", 10)
            navigation_map_qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self._navigation_map_pub = node.create_publisher(OccupancyGrid, "/navigation/map", navigation_map_qos)
            self._speed_scale_pub = node.create_publisher(Float32, "/rover_navigation/speed_scale", 10)
            node.create_subscription(String, "/rover_navigation/status", self._on_exploration_status, 10)
            service_names = {
                "start": "/rover_navigation/start_exploration",
                "pause": "/rover_navigation/pause_exploration",
                "resume": "/rover_navigation/resume_exploration",
                "stop": "/rover_navigation/stop_exploration",
            }
            self._exploration_clients = {
                action: node.create_client(Trigger, name) for action, name in service_names.items()
            }
            self._tf_buffer = Buffer()
            self._tf_listener = TransformListener(self._tf_buffer, node)
            self._time_type = Time
            node.create_timer(0.1, self._publish_speed_scale)
            self._thread = threading.Thread(target=self._executor.spin, name="rover-ros", daemon=True)
            self._thread.start()
            self._error = None
        except Exception as exc:  # pragma: no cover - depends on ROS runtime image
            self._error = f"ROS bridge 启动失败: {exc}"

    def close(self) -> None:
        if self._mapping_navigation_enabled:
            stopped, _message = self._call_exploration_trigger("stop", timeout_s=1.0)
            if stopped:
                # Let navigation and the independent safety node emit the zero-velocity interlock.
                time.sleep(0.15)
            else:
                self._publish_emergency_stop()
        self._closed = True
        process = self._mapping_process
        self._mapping_process = None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, 15)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, 9)
                except ProcessLookupError:
                    pass
        if self._executor is not None:
            try:
                self._executor.shutdown()
            except Exception:
                pass
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._node = None
        self._exploration_clients.clear()

    def sensor_snapshot(self) -> SensorSnapshot:
        now = time.monotonic()
        with self._lock:
            scan, odom, imu, battery = self._scan, self._odom, self._imu, self._battery
            error = self._error
        if not any((scan, odom, imu, battery)):
            return SensorSnapshot(
                available=False,
                error=error or "ROS 传感器主题尚未提供数据",
                battery=BatteryReading(),
                temperature=TemperatureReading(),
                imu=ImuReading(),
                lidar=LidarReading(),
            )
        def fresh(value: dict[str, Any] | None) -> bool:
            return value is not None and now - value["received"] <= self.stale_seconds
        scan_fresh = fresh(scan)
        odom_fresh = fresh(odom)
        imu_fresh = fresh(imu)
        battery_fresh = fresh(battery)
        return SensorSnapshot(
            available=scan_fresh or odom_fresh or imu_fresh or battery_fresh,
            error=None if (scan_fresh or odom_fresh or imu_fresh or battery_fresh) else "ROS 传感器数据已过期",
            battery=BatteryReading(percent=battery.get("percent") if battery_fresh and battery else None),
            temperature=TemperatureReading(),
            imu=ImuReading(yaw_rad=imu.get("yaw") if imu_fresh and imu else None),
            lidar=LidarReading(points_2d=scan.get("count") if scan_fresh and scan else None, map_quality=None),
        )

    def map_snapshot(self, *, include_data: bool = True) -> MapModel:
        with self._lock:
            grid = dict(self._map) if self._map else None
        if grid is None:
            return MapModel()
        return MapModel(
            map_id="live-map",
            name="MS200 实时地图",
            source=MapSource.MS200_TOF_2D,
            available=True,
            updated_at=grid["updated_at"],
            occupancy=OccupancyGridMeta(
                resolution_m_per_cell=grid["resolution"],
                width_cells=grid["width"],
                height_cells=grid["height"],
                origin=GridOrigin(x=grid["origin_x"], y=grid["origin_y"], yaw_rad=grid["origin_yaw"]),
                frame_id=grid["frame_id"],
                data=grid["data"] if include_data else None,
            ),
        )

    def robot_pose(self) -> RobotPoseState:
        with self._lock:
            odom = dict(self._odom) if self._odom else None
        if odom is None or time.monotonic() - odom["received"] > self.stale_seconds:
            return RobotPoseState(error="里程计数据不可用或已过期")
        if self._tf_buffer is None:
            return RobotPoseState(error="ROS TF 尚未连接")
        try:
            transform = self._tf_buffer.lookup_transform("map", odom["child_frame"], self._time_type())
            translation = transform.transform.translation
            rotation = transform.transform.rotation
            yaw = math.atan2(
                2.0 * (rotation.w * rotation.z + rotation.x * rotation.y),
                1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z),
            )
            return RobotPoseState(
                available=True,
                frame_id="map",
                x=float(translation.x),
                y=float(translation.y),
                yaw_rad=yaw,
                linear_velocity_mps=odom["linear_x"],
                angular_velocity_radps=odom["angular_z"],
                timestamp=odom["timestamp"],
            )
        except Exception as exc:
            return RobotPoseState(error=f"map 到 {odom['child_frame']} TF 不可用: {exc}")

    def mapping_status(self) -> MappingStatus:
        process = self._mapping_process
        if process is not None and process.poll() is not None and self._mapping_state not in (MappingState.IDLE, MappingState.ERROR_RECOVERABLE):
            self._mapping_state = MappingState.ERROR_RECOVERABLE
            self._mapping_error = f"SLAM 进程意外退出，exit={process.returncode}"
            self._mapping_process = None
        elif process is not None and self._mapping_state is MappingState.STARTING and self._node is not None:
            try:
                node_names = {name.lower() for name, _namespace in self._node.get_node_names_and_namespaces()}
            except Exception:
                node_names = set()
            if {"rover_ekf", "slam_toolbox"}.issubset(node_names):
                self._mapping_state = MappingState.MAPPING
                self._mapping_error = ""
        now = time.monotonic()
        with self._lock:
            latest_map = self._map
            scan = self._scan
            odom = self._odom
            imu = self._imu
        map_age = now - latest_map["received"] if latest_map else None
        scan_fresh = scan is not None and now - scan["received"] <= self.stale_seconds
        odom_fresh = odom is not None and now - odom["received"] <= self.stale_seconds
        imu_fresh = imu is not None and now - imu["received"] <= self.stale_seconds
        ready = self.enabled and self._error is None and scan is not None and odom is not None \
            and scan_fresh and odom_fresh and imu_fresh
        message = self._mapping_error or (self._error or "")
        if not self.enabled:
            message = self._error or "ROS bridge 未启用"
        return MappingStatus(
            session_id=self._mapping_session_id,
            state=self._mapping_state if self.enabled else MappingState.ERROR_RECOVERABLE,
            ready=ready,
            motion_allowed=self._mapping_state is MappingState.MAPPING and self.robot_pose().available,
            map_update_age_s=map_age,
            current_revision=self._mapping_revision,
            last_error=message,
        )

    def exploration_status(self) -> dict[str, Any]:
        with self._exploration_lock:
            return copy.deepcopy(self._exploration_status)

    def mission_state(self) -> MissionState:
        status = self.exploration_status()
        state = status.get("state", "idle")
        mode = MissionMode.AUTONOMY if state in {"starting", "exploring"} else (
            MissionMode.PAUSED if state in {"paused", "error"} else MissionMode.IDLE
        )
        target = status.get("current_target")
        try:
            current_target = Coordinate2D.model_validate(target) if target is not None else None
        except Exception:
            current_target = None
        message = str(status.get("message") or "待命")
        objective = "边缘优先自主探索" if state in {"starting", "exploring", "paused"} else "等待任务"
        return MissionState(
            mode=mode,
            objective=objective,
            status_line=message,
            exploration_state=state if state in {"idle", "starting", "exploring", "paused", "complete", "stopped", "error"} else "error",
            exploration_message=message,
            current_target=current_target,
            completed_frontiers=max(0, int(status.get("completed_frontiers", 0))),
            failed_frontiers=max(0, int(status.get("failed_frontiers", 0))),
            remaining_frontiers=max(0, int(status.get("remaining_frontiers", 0))),
        )

    def update_zones(self, zones: list[Zone]) -> None:
        with self._exploration_lock:
            self._zones = [zone.model_copy(deep=True) for zone in zones]
            map_message = copy.deepcopy(self._map_message)
        if map_message is not None:
            self._publish_navigation_map(map_message)

    def _publish_speed_scale(self) -> None:
        publisher = self._speed_scale_pub
        if publisher is None:
            return
        try:
            from std_msgs.msg import Float32

            pose = self.robot_pose()
            with self._exploration_lock:
                zones = [zone.model_copy(deep=True) for zone in self._zones]
            scale = slow_zone_scale_at(pose.x, pose.y, zones) if pose.available and pose.x is not None and pose.y is not None else 0.0
            message = Float32()
            message.data = float(scale)
            publisher.publish(message)
        except Exception as exc:
            self._error = f"无法发布区域限速状态: {exc}"

    def _on_exploration_status(self, message: Any) -> None:
        try:
            payload = json.loads(message.data)
            if not isinstance(payload, dict):
                raise ValueError("status payload must be an object")
            allowed = {"idle", "starting", "exploring", "paused", "complete", "stopped", "error"}
            if payload.get("state") not in allowed:
                raise ValueError("unknown exploration state")
            with self._exploration_lock:
                self._exploration_status = {
                    "state": payload["state"],
                    "message": str(payload.get("message") or ""),
                    "current_target": payload.get("current_target"),
                    "completed_frontiers": max(0, int(payload.get("completed_frontiers", 0))),
                    "failed_frontiers": max(0, int(payload.get("failed_frontiers", 0))),
                    "remaining_frontiers": max(0, int(payload.get("remaining_frontiers", 0))),
                    "updated_at": time.time(),
                }
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._error = f"自主探索状态消息无效: {exc}"

    def _publish_navigation_map(self, message: Any) -> None:
        publisher = self._navigation_map_pub
        if publisher is None:
            return
        try:
            from app.models.map import GridOrigin

            output = copy.deepcopy(message)
            info = output.info
            orientation = info.origin.orientation
            yaw = math.atan2(
                2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
                1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
            )
            with self._exploration_lock:
                zones = [zone.model_copy(deep=True) for zone in self._zones]
            output.data = overlay_restricted_zones(
                list(output.data),
                int(info.width),
                int(info.height),
                float(info.resolution),
                GridOrigin(x=float(info.origin.position.x), y=float(info.origin.position.y), yaw_rad=yaw),
                zones,
            )
            publisher.publish(output)
        except Exception as exc:
            self._error = f"无法生成受限区导航地图: {exc}"

    def _call_exploration_trigger(self, action: str, timeout_s: float = 2.0) -> tuple[bool, str]:
        client = self._exploration_clients.get(action)
        if client is None or self._node is None:
            return False, "自主探索 ROS 服务不可用"
        deadline = time.monotonic() + timeout_s
        try:
            from std_srvs.srv import Trigger

            while time.monotonic() < deadline and not self._closed:
                if client.wait_for_service(timeout_sec=min(0.2, max(0.01, deadline - time.monotonic()))):
                    break
            else:
                return False, "自主探索 ROS 服务未就绪"
            future = client.call_async(Trigger.Request())
            completed = threading.Event()
            future.add_done_callback(lambda _future: completed.set())
            if not completed.wait(max(0.01, deadline - time.monotonic())):
                return False, "自主探索 ROS 服务响应超时"
            response = future.result()
            return bool(response.success), str(response.message)
        except Exception as exc:
            return False, f"自主探索 ROS 服务调用失败: {exc}"

    def start_exploration(self, session_id: str, zones: list[Zone]) -> MappingCommandResult:
        if not self.enabled or self._node is None:
            return self._mapping_rejected(self._error or "ROS bridge 未启用")
        self.update_zones(zones)
        if self._mapping_state is MappingState.IDLE:
            result = self.start_mapping(session_id, enable_navigation=True)
            if not result.accepted:
                return result
        elif self._mapping_state is MappingState.MAPPING and self._mapping_navigation_enabled:
            pass
        else:
            return self._mapping_rejected("自主探索需要从空闲状态启动；请先停止当前建图会话")

        with self._exploration_lock:
            current = self._exploration_status.get("state")
            if current in {"starting", "exploring", "paused"}:
                return self._mapping_rejected("自主探索任务已在运行")
            self._exploration_status = {
                "state": "starting",
                "message": "正在启动 Nav2 并等待安全预检",
                "current_target": None,
                "completed_frontiers": 0,
                "failed_frontiers": 0,
                "remaining_frontiers": 0,
                "updated_at": time.time(),
            }
        threading.Thread(target=self._request_exploration_start, daemon=True, name="rover-exploration-start").start()
        return MappingCommandResult(
            accepted=True,
            state=self._mapping_state,
            message="SLAM 与自主探索启动中；安全预检通过后小车才会移动",
        )

    def _request_exploration_start(self) -> None:
        accepted, message = self._call_exploration_trigger("start", timeout_s=50.0)
        if not accepted:
            with self._exploration_lock:
                self._exploration_status.update(
                    state="error",
                    message=message or "自主探索启动失败",
                    updated_at=time.time(),
                )

    def start_mapping(self, session_id: str, *, enable_navigation: bool = False) -> MappingCommandResult:
        status = self.mapping_status()
        if not status.ready:
            return self._mapping_rejected(status.last_error or "雷达、里程计和 IMU 必须先稳定在线")
        if self._mapping_state is not MappingState.IDLE:
            return self._mapping_rejected("建图只能从 idle 状态启动")
        if self._node is None:
            return self._mapping_rejected("ROS 图尚未连接，无法检查重复定位或建图节点")
        try:
            node_names = [name.lower() for name, _namespace in self._node.get_node_names_and_namespaces()]
        except Exception as exc:
            return self._mapping_rejected(f"无法检查 ROS 图中的定位和建图节点: {exc}")
        conflicts = [
            name for name in node_names
            if any(component in name for component in (
                "slam_toolbox", "cartographer", "gmapping", "map_server", "ekf", "robot_localization",
                "controller_server", "planner_server", "bt_navigator", "rover_navigation", "rover_safety",
            ))
        ]
        if conflicts:
            return self._mapping_rejected("ROS 图中已有定位或建图节点运行: " + ", ".join(sorted(conflicts)))
        if enable_navigation:
            try:
                velocity_publishers = self._node.get_publishers_info_by_topic("/cmd_vel")
            except Exception as exc:
                return self._mapping_rejected(f"无法验证安全速度出口，拒绝启动自主探索: {exc}")
            if velocity_publishers:
                writers = []
                for endpoint in velocity_publishers:
                    name = str(getattr(endpoint, "node_name", "") or "")
                    namespace = str(getattr(endpoint, "node_namespace", "") or "")
                    if not name or "UNKNOWN" in name.upper():
                        writers.append("节点名未知")
                    else:
                        writers.append(f"{namespace.rstrip('/')}/{name}" if namespace else name)
                return self._mapping_rejected(
                    "底盘 /cmd_vel 已有发布者（" + ", ".join(sorted(set(writers)))
                    + "）；为避免绕过安全门控，拒绝启动自主探索"
                )
        try:
            self.mapping_session_dir.mkdir(parents=True, exist_ok=True)
            command = [*self.mapping_launch_command, f"session_dir:={self.mapping_session_dir}"]
            if enable_navigation:
                command.append("enable_navigation:=true")
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except (OSError, ValueError) as exc:
            self._mapping_state = MappingState.ERROR_RECOVERABLE
            self._mapping_error = f"无法启动 SLAM runtime: {exc}"
            return self._mapping_rejected(self._mapping_error)
        self._mapping_process = process
        self._mapping_state = MappingState.STARTING
        self._mapping_session_id = session_id
        self._mapping_error = ""
        self._mapping_navigation_enabled = enable_navigation
        if not enable_navigation:
            with self._exploration_lock:
                self._exploration_status = {
                    "state": "idle",
                    "message": "纯 SLAM 建图；网页自动探索尚未启动",
                    "current_target": None,
                    "completed_frontiers": 0,
                    "failed_frontiers": 0,
                    "remaining_frontiers": 0,
                    "updated_at": time.time(),
                }
        message = "SLAM 与 Nav2 已启动，等待地图和安全预检" if enable_navigation else "SLAM 已启动，等待首张真实地图"
        return MappingCommandResult(accepted=True, state=self._mapping_state, message=message)

    def pause_mapping(self) -> MappingCommandResult:
        if self._mapping_state is not MappingState.MAPPING:
            return self._mapping_rejected("只有建图中可以暂停")
        if self._mapping_navigation_enabled and self.exploration_status().get("state") in {"starting", "exploring"}:
            accepted, message = self._call_exploration_trigger("pause")
            if not accepted:
                return self._mapping_rejected(message)
        result = self._call_pause_toggle()
        if not result.accepted:
            return result
        self._mapping_state = MappingState.PAUSED
        return MappingCommandResult(accepted=True, state=self._mapping_state, message="SLAM 已暂停接收扫描")

    def resume_mapping(self) -> MappingCommandResult:
        if self._mapping_state is not MappingState.PAUSED:
            return self._mapping_rejected("只有暂停状态可以恢复")
        status = self.mapping_status()
        if not status.ready or not self.robot_pose().available:
            return self._mapping_rejected("恢复前需要新鲜传感器数据和有效 map 位姿")
        result = self._call_pause_toggle()
        if not result.accepted:
            return result
        if self._mapping_navigation_enabled and self.exploration_status().get("state") == "paused":
            accepted, message = self._call_exploration_trigger("resume")
            if not accepted:
                return self._mapping_rejected(message)
        self._mapping_state = MappingState.MAPPING
        return MappingCommandResult(accepted=True, state=self._mapping_state, message="SLAM 已恢复接收扫描")

    def save_mapping(self, map_name: str) -> MappingCommandResult:
        if self._mapping_state not in (MappingState.MAPPING, MappingState.PAUSED):
            return self._mapping_rejected("只有活动或暂停中的建图会话可以保存")
        if not self.map_snapshot().available:
            return self._mapping_rejected("当前会话尚未生成真实 OccupancyGrid，无法保存")
        status_before = self._mapping_state
        self._mapping_state = MappingState.SAVING
        target = self.mapping_session_dir / map_name
        try:
            serialized = subprocess.run(
                [
                    "ros2", "service", "call", "/slam_toolbox/serialize_map",
                    "slam_toolbox/srv/SerializePoseGraph", f"{{filename: '{target}'}}",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
            )
            if serialized.returncode != 0 or not re.search(r"\bresult\s*[=:]\s*0\b", serialized.stdout):
                raise RuntimeError(serialized.stdout[-1000:] or "SLAM pose graph serialization failed")
            completed = subprocess.run(
                ["ros2", "run", "nav2_map_server", "map_saver_cli", "-f", str(target), "--ros-args", "-p", "save_map_timeout:=10.0"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
            )
            if completed.returncode != 0 or not target.with_suffix(".yaml").is_file() or not target.with_suffix(".pgm").is_file() or not target.with_suffix(".posegraph").is_file():
                raise RuntimeError(completed.stdout[-1000:] or "map_saver_cli did not create a complete map")
            self._mapping_revision = map_name
            self._mapping_state = status_before
            return MappingCommandResult(accepted=True, state=self._mapping_state, message=f"地图已保存为 {map_name}")
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            self._mapping_state = status_before
            return self._mapping_rejected(f"地图保存失败: {exc}")

    def load_mapping(self, request: Any) -> MappingCommandResult:
        if self._mapping_state not in (MappingState.IDLE, MappingState.PAUSED):
            return self._mapping_rejected("加载地图只能从 idle 或 paused 状态开始")
        target = self.mapping_session_dir / request.map_name
        if not target.with_suffix(".posegraph").is_file():
            return self._mapping_rejected(f"找不到已保存的 SLAM pose graph: {target.name}")
        if self._mapping_state is MappingState.IDLE:
            started = self.start_mapping(request.session_id)
            if not started.accepted:
                return started
        try:
            completed = subprocess.run(
                [
                    "ros2", "service", "call", "/slam_toolbox/deserialize_map",
                    "slam_toolbox/srv/DeserializePoseGraph",
                    "{filename: '%s', match_type: %d, initial_pose: {x: %.6f, y: %.6f, theta: %.6f}}"
                    % (target, request.match_type, request.x, request.y, request.yaw),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=25,
            )
            if completed.returncode != 0 or not re.search(r"\bresult\s*[=:]\s*0\b", completed.stdout):
                raise RuntimeError(completed.stdout[-1000:] or "SLAM pose graph load failed")
            pause = self._call_pause_toggle()
            if not pause.accepted:
                raise RuntimeError(pause.message)
            self._mapping_state = MappingState.PAUSED
            self._mapping_session_id = request.session_id
            self._mapping_revision = request.map_name
            return MappingCommandResult(accepted=True, state=self._mapping_state, message="地图和 pose graph 已加载；恢复前请确认位置")
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            self._mapping_state = MappingState.ERROR_RECOVERABLE
            self._mapping_error = f"地图加载失败: {exc}"
            return self._mapping_rejected(self._mapping_error)

    def stop_mapping(self) -> MappingCommandResult:
        navigation_enabled = self._mapping_navigation_enabled
        if self._mapping_state is MappingState.ERROR_RECOVERABLE and self._mapping_process is None:
            self._mapping_state = MappingState.IDLE
            self._mapping_error = ""
            self._mapping_navigation_enabled = False
            return MappingCommandResult(accepted=True, state=self._mapping_state, message="建图错误状态已清理")
        if self._mapping_state not in (MappingState.MAPPING, MappingState.PAUSED, MappingState.STARTING, MappingState.ERROR_RECOVERABLE):
            return self._mapping_rejected("没有可停止的建图会话")
        exploration_stop_confirmed = True
        emergency_stop_sent = False
        if navigation_enabled:
            accepted, message = self._call_exploration_trigger("stop", timeout_s=2.0)
            if not accepted:
                exploration_stop_confirmed = False
                emergency_stop_sent = self._publish_emergency_stop()
                with self._exploration_lock:
                    self._exploration_status.update(state="stopped", message=message, updated_at=time.time())
            else:
                # Navigation publishes the interlock immediately; allow the safety node to emit zero before shutdown.
                time.sleep(0.15)
        process = self._mapping_process
        if process is None or process.poll() is not None:
            self._mapping_process = None
            self._mapping_state = MappingState.IDLE
            self._mapping_error = ""
            self._mapping_navigation_enabled = False
            message = "已清理已退出的建图进程状态"
            if navigation_enabled and not exploration_stop_confirmed:
                stop_detail = "已向安全门控发送急停；" if emergency_stop_sent else "未能确认安全门控急停连接；"
                message = "自主探索停止服务未响应，" + stop_detail + message
            return MappingCommandResult(accepted=True, state=self._mapping_state, message=message)
        map_available = self.map_snapshot().available
        save_result = self.save_mapping(self._mapping_session_id or "map") \
            if self._mapping_state in (MappingState.MAPPING, MappingState.PAUSED) and map_available else None
        try:
            os.killpg(process.pid, 15)
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 9)
            process.wait(timeout=2)
        except ProcessLookupError:
            pass
        self._mapping_process = None
        self._mapping_state = MappingState.IDLE
        self._mapping_error = ""
        self._mapping_navigation_enabled = False
        if save_result is not None and not save_result.accepted:
            return MappingCommandResult(accepted=False, state=self._mapping_state, message=f"SLAM 已停止，但自动保存失败：{save_result.message}")
        message = "建图已停止并保存" if save_result is not None else "建图已停止；首张地图尚未生成，未执行保存"
        if navigation_enabled and not exploration_stop_confirmed:
            stop_detail = "已向安全门控发送急停；" if emergency_stop_sent else "未能确认安全门控急停连接；"
            message = "自主探索停止服务未响应，" + stop_detail + message
        return MappingCommandResult(accepted=True, state=self._mapping_state, message=message)

    def _publish_emergency_stop(self) -> bool:
        publisher = self._emergency_stop_pub
        if publisher is None:
            return False
        try:
            from std_msgs.msg import Bool

            message = Bool()
            message.data = True
            # Repeat briefly so the independent safety process receives the stop before launch teardown.
            connected = False
            for _ in range(5):
                publisher.publish(message)
                try:
                    connected = connected or publisher.get_subscription_count() > 0
                except Exception:
                    pass
                time.sleep(0.05)
            return connected
        except Exception:
            return False

    def _call_pause_toggle(self) -> MappingCommandResult:
        try:
            completed = subprocess.run(
                [
                    "ros2",
                    "service",
                    "call",
                    "/slam_toolbox/pause_new_measurements",
                    "slam_toolbox/srv/Pause",
                    "{}",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=12,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stdout[-800:] or "SLAM measurement pause toggle failed")
            return MappingCommandResult(
                accepted=True,
                state=self._mapping_state,
                message="SLAM 扫描接收状态已切换",
            )
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            return self._mapping_rejected(str(exc))

    def _mapping_rejected(self, message: str) -> MappingCommandResult:
        return MappingCommandResult(accepted=False, state=self._mapping_state, message=message)

    def radar_scan(self) -> RadarScan:
        with self._lock:
            scan = dict(self._scan) if self._scan else None
            error = self._error
        if scan is None or time.monotonic() - scan["received"] > self.stale_seconds:
            return RadarScan(available=False, error=error or "MS200 雷达数据不可用")
        return RadarScan(
            available=True,
            frame_id=scan["frame_id"],
            timestamp=scan["timestamp"],
            angle_min_rad=scan["angle_min"],
            angle_max_rad=scan["angle_max"],
            range_min_m=scan["range_min"],
            range_max_m=scan["range_max"],
            points=scan["points"],
        )

    def gimbal_state(self) -> GimbalState:
        with self._lock:
            pan, tilt, updated = self._gimbal["pan_deg"], self._gimbal["tilt_deg"], self._gimbal["updated"]
            error = self._error
        available = self._pan_pub is not None and self._tilt_pub is not None \
            and self._pan_pub.get_subscription_count() > 0 and self._tilt_pub.get_subscription_count() > 0
        return GimbalState(
            available=available,
            pan_deg=pan,
            tilt_deg=tilt,
            error=None if available else error or "云台 ROS 发布器不可用",
            updated_at=datetime.fromtimestamp(updated, timezone.utc) if updated else datetime.now(timezone.utc),
        )

    def command_gimbal(self, pan_deg: float | None, tilt_deg: float | None) -> GimbalState:
        if self._pan_pub is None or self._tilt_pub is None:
            raise RuntimeError(self._error or "云台 ROS 发布器不可用")
        try:
            if self._pan_pub.get_subscription_count() == 0 or self._tilt_pub.get_subscription_count() == 0:
                raise RuntimeError("云台控制话题没有设备订阅者")
            from std_msgs.msg import Int32
            if pan_deg is not None:
                message = Int32()
                message.data = int(round(pan_deg))
                self._pan_pub.publish(message)
            if tilt_deg is not None:
                message = Int32()
                message.data = int(round(tilt_deg))
                self._tilt_pub.publish(message)
            with self._lock:
                if pan_deg is not None:
                    self._gimbal["pan_deg"] = pan_deg
                if tilt_deg is not None:
                    self._gimbal["tilt_deg"] = tilt_deg
                self._gimbal["updated"] = time.time()
            return self.gimbal_state()
        except Exception as exc:
            raise RuntimeError(f"云台命令发布失败: {exc}") from exc

    def _on_scan(self, message: Any) -> None:
        points: list[RadarPoint] = []
        stride = max(1, len(message.ranges) // 720)
        for index in range(0, len(message.ranges), stride):
            distance = float(message.ranges[index])
            if not math.isfinite(distance) or distance < message.range_min or distance > message.range_max:
                continue
            angle = message.angle_min + index * message.angle_increment
            points.append(RadarPoint(angle_rad=angle, range_m=distance, x_m=distance * math.cos(angle), y_m=distance * math.sin(angle)))
        with self._lock:
            self._scan = {
                "received": time.monotonic(),
                "timestamp": datetime.now(timezone.utc),
                "frame_id": message.header.frame_id or "laser_frame",
                "angle_min": float(message.angle_min),
                "angle_max": float(message.angle_max),
                "range_min": float(message.range_min),
                "range_max": float(message.range_max),
                "count": len(points),
                "points": points,
            }

    def _on_odom(self, message: Any) -> None:
        q = message.pose.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        with self._lock:
            self._odom = {
                "received": time.monotonic(),
                "timestamp": datetime.now(timezone.utc),
                "x": float(message.pose.pose.position.x),
                "y": float(message.pose.pose.position.y),
                "yaw": yaw,
                "linear_x": float(message.twist.twist.linear.x),
                "angular_z": float(message.twist.twist.angular.z),
                "frame_id": message.header.frame_id or "odom",
                "child_frame": message.child_frame_id or "base_footprint",
            }

    def _on_imu(self, message: Any) -> None:
        q = message.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        with self._lock:
            self._imu = {"received": time.monotonic(), "yaw": yaw}

    def _on_battery(self, message: Any) -> None:
        with self._lock:
            self._battery = {"received": time.monotonic(), "percent": float(message.data)}

    def _on_map(self, message: Any) -> None:
        info = message.info
        origin_q = info.origin.orientation
        origin_yaw = math.atan2(
            2.0 * (origin_q.w * origin_q.z + origin_q.x * origin_q.y),
            1.0 - 2.0 * (origin_q.y * origin_q.y + origin_q.z * origin_q.z),
        )
        expected = int(info.width) * int(info.height)
        if expected < 1 or expected > 1_000_000 or len(message.data) != expected:
            return
        now = time.monotonic()
        with self._lock:
            self._map = {
                "received": now,
                "updated_at": datetime.now(timezone.utc),
                "width": int(info.width),
                "height": int(info.height),
                "resolution": float(info.resolution),
                "origin_x": float(info.origin.position.x),
                "origin_y": float(info.origin.position.y),
                "origin_yaw": origin_yaw,
                "frame_id": message.header.frame_id or "map",
                "data": [int(value) for value in message.data],
            }
            self._map_message = copy.deepcopy(message)
        self._publish_navigation_map(message)
        if self._mapping_state is MappingState.STARTING:
            self._mapping_state = MappingState.MAPPING
