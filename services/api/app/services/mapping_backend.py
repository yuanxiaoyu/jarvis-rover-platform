"""Backends for the mapping-session API."""

from __future__ import annotations

import asyncio
from typing import Protocol

from app.models.mapping import (
    MappingCommandResult,
    MappingState,
    MappingStatus,
    PoseRequest,
)


class MappingBackend(Protocol):
    async def status(self) -> MappingStatus: ...

    async def start(self, session_id: str) -> MappingCommandResult: ...

    async def pause(self) -> MappingCommandResult: ...

    async def resume(self) -> MappingCommandResult: ...

    async def stop(self) -> MappingCommandResult: ...

    async def save(self, map_name: str) -> MappingCommandResult: ...

    async def load(self, request: PoseRequest) -> MappingCommandResult: ...

    async def close(self) -> None: ...




class UnavailableMappingBackend:
    """Fail-closed backend used when no real ROS mapping service is connected."""

    _message = "真实 mapping backend 不可用"

    async def status(self) -> MappingStatus:
        return MappingStatus(
            state=MappingState.ERROR_RECOVERABLE,
            ready=False,
            motion_allowed=False,
            last_error=self._message,
        )

    async def start(self, session_id: str) -> MappingCommandResult:
        return self._rejected()

    async def pause(self) -> MappingCommandResult:
        return self._rejected()

    async def resume(self) -> MappingCommandResult:
        return self._rejected()

    async def stop(self) -> MappingCommandResult:
        return self._rejected()

    async def save(self, map_name: str) -> MappingCommandResult:
        return self._rejected()

    async def load(self, request: PoseRequest) -> MappingCommandResult:
        return self._rejected()

    async def close(self) -> None:
        return None

    def _rejected(self) -> MappingCommandResult:
        return MappingCommandResult(
            accepted=False,
            state=MappingState.ERROR_RECOVERABLE,
            message=self._message,
        )


class RosRuntimeMappingBackend:
    """Async facade over the process and sensor state owned by RosRuntimeStore."""

    def __init__(self, runtime: object) -> None:
        self._runtime = runtime

    async def status(self) -> MappingStatus:
        return self._runtime.mapping_status()

    async def start(self, session_id: str) -> MappingCommandResult:
        return await asyncio.to_thread(self._runtime.start_mapping, session_id)

    async def pause(self) -> MappingCommandResult:
        return await asyncio.to_thread(self._runtime.pause_mapping)

    async def resume(self) -> MappingCommandResult:
        return await asyncio.to_thread(self._runtime.resume_mapping)

    async def stop(self) -> MappingCommandResult:
        return await asyncio.to_thread(self._runtime.stop_mapping)

    async def save(self, map_name: str) -> MappingCommandResult:
        return await asyncio.to_thread(self._runtime.save_mapping, map_name)

    async def load(self, request: PoseRequest) -> MappingCommandResult:
        return await asyncio.to_thread(self._runtime.load_mapping, request)

    async def close(self) -> None:
        return None


class InMemoryMappingBackend:
    """Deterministic backend for development and API tests.

    It deliberately does not claim to create a map.  ``mark_mapping`` is a
    small test/development hook that simulates the asynchronous ROS start
    completing.
    """

    def __init__(self) -> None:
        self._status = MappingStatus()

    async def status(self) -> MappingStatus:
        return self._status.model_copy(deep=True)

    async def start(self, session_id: str) -> MappingCommandResult:
        if self._status.state is not MappingState.IDLE:
            return self._rejected("start is only valid from idle")
        self._status = MappingStatus(
            session_id=session_id,
            state=MappingState.STARTING,
            ready=False,
            motion_allowed=False,
        )
        return self._accepted("mapping start queued")

    async def pause(self) -> MappingCommandResult:
        if self._status.state is not MappingState.MAPPING:
            return self._rejected("pause is only valid while mapping")
        self._status.state = MappingState.PAUSED
        self._status.motion_allowed = False
        self._status.ready = False
        return self._accepted("mapping pause queued")

    async def resume(self) -> MappingCommandResult:
        if self._status.state is not MappingState.PAUSED:
            return self._rejected("resume is only valid while paused")
        self._status.state = MappingState.MAPPING
        self._status.ready = True
        self._status.motion_allowed = True
        return self._accepted("mapping resume queued")

    async def stop(self) -> MappingCommandResult:
        if self._status.state not in (MappingState.MAPPING, MappingState.PAUSED):
            return self._rejected("stop is only valid while mapping or paused")
        self._status.state = MappingState.IDLE
        self._status.ready = False
        self._status.motion_allowed = False
        return self._accepted("mapping stop queued")

    async def save(self, map_name: str) -> MappingCommandResult:
        if self._status.state not in (MappingState.MAPPING, MappingState.PAUSED):
            return self._rejected("save is only valid while mapping or paused")
        previous = self._status.state
        self._status.state = MappingState.SAVING
        self._status.ready = False
        self._status.motion_allowed = False
        self._status.current_revision = map_name
        self._status.state = previous
        self._status.ready = previous is MappingState.MAPPING
        self._status.motion_allowed = previous is MappingState.MAPPING
        return self._accepted("mapping save queued")

    async def load(self, request: PoseRequest) -> MappingCommandResult:
        if self._status.state not in (MappingState.IDLE, MappingState.PAUSED):
            return self._rejected("load is only valid from idle or paused")
        self._status = MappingStatus(
            session_id=request.session_id,
            state=MappingState.PAUSED,
            ready=False,
            motion_allowed=False,
            current_revision=request.session_id,
        )
        return self._accepted("mapping load queued; explicit resume is required")

    def mark_mapping(self) -> None:
        if self._status.state is not MappingState.STARTING:
            raise RuntimeError("mapping start is not pending")
        self._status.state = MappingState.MAPPING
        self._status.ready = True
        self._status.motion_allowed = True

    def mark_error(self, message: str) -> None:
        self._status.state = MappingState.ERROR_RECOVERABLE
        self._status.ready = False
        self._status.motion_allowed = False
        self._status.last_error = message

    async def close(self) -> None:
        return None

    def _accepted(self, message: str) -> MappingCommandResult:
        return MappingCommandResult(
            accepted=True,
            state=self._status.state,
            message=message,
        )

    def _rejected(self, message: str) -> MappingCommandResult:
        return MappingCommandResult(
            accepted=False,
            state=self._status.state,
            message=message,
        )


class RosMappingBackend:
    """Adapter from the HTTP models to the background rclpy bridge."""

    def __init__(self, bridge: "RosMappingBridge") -> None:
        self._bridge = bridge

    async def status(self) -> MappingStatus:
        return await self._bridge.status()

    async def start(self, session_id: str) -> MappingCommandResult:
        return await self._command(0, session_id=session_id)

    async def pause(self) -> MappingCommandResult:
        return await self._command(1)

    async def resume(self) -> MappingCommandResult:
        return await self._command(2)

    async def stop(self) -> MappingCommandResult:
        return await self._command(3)

    async def save(self, map_name: str) -> MappingCommandResult:
        return await self._command(4, map_name=map_name)

    async def load(self, request: PoseRequest) -> MappingCommandResult:
        return await self._command(
            5,
            session_id=request.session_id,
            map_name=request.map_name,
            match_type=request.match_type,
            x=request.x,
            y=request.y,
            yaw=request.yaw,
        )

    async def close(self) -> None:
        await self._bridge.close()

    async def _command(self, command: int, **values: object) -> MappingCommandResult:
        return await self._bridge.command(command, **values)


# Kept as a type-only import to avoid importing rclpy during API tests.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.ros_bridge import RosMappingBridge
