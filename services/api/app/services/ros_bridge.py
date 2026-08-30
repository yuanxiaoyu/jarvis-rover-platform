"""Async bridge between FastAPI and the ROS mapping service."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.models.mapping import MappingCommandResult, MappingState, MappingStatus


@dataclass(frozen=True)
class RosStatusSnapshot:
    state: int
    session_id: str
    ready: bool
    motion_allowed: bool
    map_update_age_s: float | None
    current_revision: str | None
    last_error: str
    received_at: float | None


class RosMappingBridge:
    """Run a private rclpy executor and expose awaitable operations."""

    def __init__(
        self,
        *,
        command_service: str = "/mapping/command",
        status_topic: str = "/mapping/status",
        service_timeout_seconds: float = 10.0,
        status_timeout_seconds: float = 2.0,
    ) -> None:
        if service_timeout_seconds <= 0 or status_timeout_seconds <= 0:
            raise ValueError("bridge timeouts must be positive")
        self.command_service = command_service
        self.status_topic = status_topic
        self.service_timeout_seconds = service_timeout_seconds
        self.status_timeout_seconds = status_timeout_seconds
        self._rclpy: Any = None
        self._context: Any = None
        self._node: Any = None
        self._executor: Any = None
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._command_type: Any = None
        self._started = False
        self._closed = False
        self._status_lock = threading.Lock()
        self._status = RosStatusSnapshot(
            state=0,
            session_id="",
            ready=False,
            motion_allowed=False,
            map_update_age_s=None,
            current_revision=None,
            last_error="",
            received_at=None,
        )

    async def start(self) -> None:
        if self._started:
            return
        if self._closed:
            raise RuntimeError("ROS mapping bridge is closed")
        try:
            (
                self._rclpy,
                context_type,
                node_type,
                executor_type,
                qos_type,
                reliability,
                durability,
                history,
                command_type,
                status_type,
            ) = _load_ros_symbols()
            self._context = context_type()
            self._rclpy.init(context=self._context)
            self._node = node_type("rover_api_bridge", context=self._context)
            qos = qos_type(
                history=history.KEEP_LAST,
                depth=10,
                reliability=reliability.RELIABLE,
                durability=durability.VOLATILE,
            )
            self._client = self._node.create_client(command_type, self.command_service)
            self._command_type = command_type
            self._node.create_subscription(status_type, self.status_topic, self._status_callback, qos)
            self._executor = executor_type(num_threads=2, context=self._context)
            self._executor.add_node(self._node)
            self._thread = threading.Thread(
                target=self._executor.spin,
                name="rover-api-ros-executor",
                daemon=True,
            )
            self._thread.start()
            ready = await asyncio.to_thread(
                self._client.wait_for_service,
                timeout_sec=self.service_timeout_seconds,
            )
            if not ready:
                raise RuntimeError(f"mapping service unavailable: {self.command_service}")
            self._started = True
        except Exception as exc:
            await self.close()
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"unable to start ROS mapping bridge: {exc}") from exc

    async def status(self) -> MappingStatus:
        with self._status_lock:
            snapshot = self._status
        state = _api_state(snapshot.state)
        stale = (
            snapshot.received_at is None
            or time.monotonic() - snapshot.received_at > self.status_timeout_seconds
        )
        if stale:
            state = MappingState.ERROR_RECOVERABLE
        return MappingStatus(
            session_id=snapshot.session_id or None,
            state=state,
            ready=snapshot.ready and not stale,
            motion_allowed=snapshot.motion_allowed and not stale,
            map_update_age_s=snapshot.map_update_age_s,
            current_revision=snapshot.current_revision,
            last_error=("mapping status is stale" if stale else snapshot.last_error),
        )

    async def command(self, command: int, **values: object) -> MappingCommandResult:
        if not self._started or self._client is None:
            raise RuntimeError("ROS mapping bridge is not started")
        request = self._command_type.Request()
        request.command = int(command)
        if "session_id" in values:
            request.session_id = str(values["session_id"])
        if "map_name" in values:
            request.map_name = str(values["map_name"])
        if "match_type" in values:
            request.match_type = int(values["match_type"])
        if all(key in values for key in ("x", "y", "yaw")):
            request.has_initial_pose = True
            request.initial_pose.x = float(values["x"])
            request.initial_pose.y = float(values["y"])
            request.initial_pose.theta = float(values["yaw"])
        response = await self._call(request)
        state_value = int(getattr(response, "state", 5))
        return MappingCommandResult(
            accepted=bool(getattr(response, "accepted", False)),
            state=_api_state(state_value),
            message=str(getattr(response, "message", "")),
        )

    async def close(self) -> None:
        if self._closed and self._thread is None:
            return
        self._closed = True
        self._started = False
        executor = self._executor
        if executor is not None:
            try:
                executor.shutdown()
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
        if self._context is not None:
            try:
                self._context.shutdown()
            except Exception:
                pass
        self._executor = None
        self._thread = None
        self._node = None
        self._client = None
        self._command_type = None

    async def _call(self, request: Any) -> Any:
        loop = asyncio.get_running_loop()
        target = loop.create_future()
        try:
            ros_future = self._client.call_async(request)
        except Exception as exc:
            raise RuntimeError(f"mapping service call failed: {exc}") from exc

        def on_done(done_future: Any) -> None:
            try:
                result = done_future.result()
            except Exception as exc:  # pragma: no cover - middleware-specific
                loop.call_soon_threadsafe(_set_exception, target, exc)
            else:
                loop.call_soon_threadsafe(_set_result, target, result)

        ros_future.add_done_callback(on_done)
        try:
            return await asyncio.wait_for(target, timeout=self.service_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("mapping command service timed out") from exc

    def _status_callback(self, message: Any) -> None:
        with self._status_lock:
            age = float(message.map_update_age_s)
            self._status = RosStatusSnapshot(
                state=int(message.state),
                session_id=str(message.session_id),
                ready=bool(message.ready),
                motion_allowed=bool(message.motion_allowed),
                map_update_age_s=None if age < 0 else age,
                current_revision=str(message.current_revision) or None,
                last_error=str(message.last_error),
                received_at=time.monotonic(),
            )


def _load_ros_symbols() -> tuple[Any, ...]:
    try:
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from rover_interfaces.msg import MappingSession
        from rover_interfaces.srv import MappingCommand
    except ImportError as exc:  # pragma: no cover - depends on ROS install
        raise RuntimeError("ROS mapping dependencies are unavailable") from exc
    return (
        rclpy,
        Context,
        Node,
        MultiThreadedExecutor,
        QoSProfile,
        ReliabilityPolicy,
        DurabilityPolicy,
        HistoryPolicy,
        MappingCommand,
        MappingSession,
    )


def _api_state(value: int) -> MappingState:
    return {
        0: MappingState.IDLE,
        1: MappingState.STARTING,
        2: MappingState.MAPPING,
        3: MappingState.PAUSED,
        4: MappingState.SAVING,
        5: MappingState.ERROR_RECOVERABLE,
    }.get(value, MappingState.ERROR_RECOVERABLE)


def _set_result(future: asyncio.Future[Any], result: Any) -> None:
    if not future.done():
        future.set_result(result)


def _set_exception(future: asyncio.Future[Any], error: BaseException) -> None:
    if not future.done():
        future.set_exception(error)
