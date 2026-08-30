"""Small, testable gateway for SLAM Toolbox services."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from threading import Event
from typing import Any, Protocol

from .map_validation import Pose2D


class SlamGateway(Protocol):
    def services_ready(self) -> bool: ...

    def pause(self, paused: bool) -> bool: ...

    def clear_queue(self) -> bool: ...

    def save_map(self, path_without_extension: str) -> bool: ...

    def serialize_pose_graph(self, filename: str) -> bool: ...

    def deserialize_pose_graph(
        self, filename: str, match_type: int, pose: Pose2D
    ) -> bool: ...


DEFAULT_SERVICE_SUFFIXES = {
    "pause": "pause_new_measurements",
    "clear_queue": "clear_queue",
    "save_map": "save_map",
    "serialize_pose_graph": "serialize_map",
    "deserialize_pose_graph": "deserialize_map",
}
OPTIONAL_SERVICE_KEYS = {"clear_queue"}


class RosSlamGateway:
    """Call SLAM Toolbox without blocking an rclpy executor callback.

    The node's executor must continue spinning while these methods wait.  The
    mapping node invokes them from its worker thread, not from a service
    callback, so the executor can deliver the asynchronous response.
    """

    def __init__(
        self,
        node: Any,
        *,
        prefix: str = "/slam_toolbox",
        timeout_s: float = 10.0,
        service_suffixes: Mapping[str, str] | None = None,
        service_types: Mapping[str, Any] | None = None,
        client_factory: Callable[[Any, str], Any] | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.node = node
        self.timeout_s = timeout_s
        self.prefix = prefix.rstrip("/")
        suffixes = dict(DEFAULT_SERVICE_SUFFIXES)
        if service_suffixes:
            suffixes.update(service_suffixes)
        self.service_names = {
            key: self._join_name(suffix) for key, suffix in suffixes.items()
        }
        types = dict(service_types or _load_service_types())
        missing = sorted(set(self.service_names) - set(types))
        if missing:
            raise ValueError(f"missing SLAM service types: {', '.join(missing)}")
        factory = client_factory or node.create_client
        self._service_types = types
        self._paused: bool | None = None
        self._clients = {
            key: factory(types[key], self.service_names[key])
            for key in self.service_names
        }

    def services_ready(self) -> bool:
        return all(
            _wait_for_service(client, 0.0)
            for key, client in self._clients.items()
            if key not in OPTIONAL_SERVICE_KEYS
        )

    def pause(self, paused: bool) -> bool:
        """Toggle Humble's pause service until it reports the desired state."""
        desired = bool(paused)
        if self._paused is desired:
            return True
        request = self._service_types["pause"].Request()
        for _attempt in range(2):
            response = self._call_response("pause", request)
            if response is None:
                return False
            status = getattr(response, "status", None)
            if not isinstance(status, bool):
                self._log_error("SLAM pause response has no boolean status")
                return False
            self._paused = status
            if status is desired:
                return True
        self._log_error("SLAM pause toggle did not reach requested state")
        return False

    def clear_queue(self) -> bool:
        client = self._clients["clear_queue"]
        if not _wait_for_service(client, 0.0):
            self._log_warning(
                "SLAM Toolbox has no clear_queue endpoint; relying on pause to stop queued scans"
            )
            return True
        request = self._service_types["clear_queue"].Request()
        return self._call("clear_queue", request, _status_response)

    def save_map(self, path_without_extension: str) -> bool:
        request = self._service_types["save_map"].Request()
        name = _new_string_message()
        name.data = path_without_extension
        request.name = name
        return self._call("save_map", request, _result_response)

    def serialize_pose_graph(self, filename: str) -> bool:
        request = self._service_types["serialize_pose_graph"].Request()
        request.filename = filename
        return self._call("serialize_pose_graph", request, _result_response)

    def deserialize_pose_graph(
        self, filename: str, match_type: int, pose: Pose2D
    ) -> bool:
        request = self._service_types["deserialize_pose_graph"].Request()
        request.filename = filename
        request.match_type = int(match_type)
        _assign_initial_pose(request, pose)
        return self._call("deserialize_pose_graph", request, _deserialize_response)

    def _call(
        self, key: str, request: Any, checker: Callable[[Any], bool]
    ) -> bool:
        response = self._call_response(key, request)
        return response is not None and checker(response)

    def _call_response(self, key: str, request: Any) -> Any | None:
        client = self._clients[key]
        if not _wait_for_service(client, self.timeout_s):
            self._log_error(f"SLAM service unavailable: {self.service_names[key]}")
            return None
        try:
            future = client.call_async(request)
        except Exception as exc:  # pragma: no cover - middleware-specific
            self._log_error(f"SLAM service call failed: {self.service_names[key]}: {exc}")
            return None

        completed = Event()
        response: list[Any] = []
        error: list[BaseException] = []

        def on_done(done_future: Any) -> None:
            try:
                response.append(done_future.result())
            except BaseException as exc:  # pragma: no cover - middleware-specific
                error.append(exc)
            finally:
                completed.set()

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(on_done)
        else:  # Keep the seam friendly to tiny fake clients.
            response.append(future)
            completed.set()
        if not completed.wait(self.timeout_s):
            self._log_error(f"SLAM service timed out: {self.service_names[key]}")
            return None
        if error or not response:
            detail = str(error[0]) if error else "empty response"
            self._log_error(f"SLAM service returned no response: {detail}")
            return None
        return response[0]

    def _join_name(self, suffix: str) -> str:
        if not suffix:
            raise ValueError("SLAM service suffix cannot be empty")
        if suffix.startswith("/"):
            return suffix
        return f"{self.prefix}/{suffix}"

    def _log_warning(self, message: str) -> None:
        logger = getattr(self.node, "get_logger", lambda: None)()
        if logger is not None and hasattr(logger, "warning"):
            logger.warning(message)

    def _log_error(self, message: str) -> None:
        logger = getattr(self.node, "get_logger", lambda: None)()
        if logger is not None and hasattr(logger, "error"):
            logger.error(message)


def _load_service_types() -> dict[str, Any]:
    try:
        from slam_toolbox.srv import (  # type: ignore[import-not-found]
            ClearQueue,
            DeserializePoseGraph,
            Pause,
            SaveMap,
            SerializePoseGraph,
        )
    except ImportError as exc:  # pragma: no cover - depends on ROS install
        raise RuntimeError("slam_toolbox service types are unavailable") from exc
    return {
        "pause": Pause,
        "clear_queue": ClearQueue,
        "save_map": SaveMap,
        "serialize_pose_graph": SerializePoseGraph,
        "deserialize_pose_graph": DeserializePoseGraph,
    }


def _wait_for_service(client: Any, timeout_s: float) -> bool:
    try:
        return bool(client.wait_for_service(timeout_sec=timeout_s))
    except TypeError:
        return bool(client.wait_for_service(timeout_s))
    except Exception:
        return False


def _status_response(response: Any) -> bool:
    return getattr(response, "status", None) is True


def _result_response(response: Any) -> bool:
    result = getattr(response, "result", None)
    if result is None:
        return False
    success = getattr(type(response), "RESULT_SUCCESS", 0)
    return result == success


def _deserialize_response(response: Any) -> bool:
    # Humble's DeserializePoseGraph response is empty; transport completion is
    # the success signal.  If a future version adds a result/status field, it
    # must still explicitly report success.
    if hasattr(response, "result"):
        return _result_response(response)
    if hasattr(response, "status"):
        return _status_response(response)
    return True


def _new_string_message() -> Any:
    try:
        from std_msgs.msg import String  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on ROS install
        raise RuntimeError("std_msgs String is unavailable") from exc
    return String()


def _assign_initial_pose(request: Any, pose: Pose2D) -> None:
    target = getattr(request, "initial_pose", None)
    if target is not None and hasattr(target, "theta"):
        target.x = pose.x
        target.y = pose.y
        target.theta = pose.yaw
        return
    if target is not None and hasattr(target, "position") and hasattr(target, "orientation"):
        target.position.x = pose.x
        target.position.y = pose.y
        target.position.z = 0.0
        target.orientation.x = 0.0
        target.orientation.y = 0.0
        target.orientation.z = math.sin(pose.yaw / 2.0)
        target.orientation.w = math.cos(pose.yaw / 2.0)
        return
    request.initial_pose = _pose_message(pose)


def _pose_message(pose: Pose2D) -> Any:
    try:
        from geometry_msgs.msg import Pose2D as RosPose2D  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on ROS install
        raise RuntimeError("geometry_msgs Pose2D is unavailable") from exc
    message = RosPose2D()
    message.x = pose.x
    message.y = pose.y
    message.theta = pose.yaw
    return message
