from dataclasses import dataclass, replace
from enum import IntEnum


class MappingState(IntEnum):
    IDLE = 0
    STARTING = 1
    MAPPING = 2
    PAUSED = 3
    SAVING = 4
    ERROR_RECOVERABLE = 5


class CommandType(IntEnum):
    START = 0
    PAUSE = 1
    RESUME = 2
    STOP = 3
    SAVE = 4
    LOAD = 5


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    state: MappingState
    motion_allowed: bool
    ready: bool = False
    current_revision: str | None = None
    last_error: str = ""
    map_update_age_s: float | None = None


@dataclass(frozen=True)
class CommandResult:
    accepted: bool
    message: str


class SessionError(RuntimeError):
    pass


class SessionController:
    def __init__(self, session_id: str) -> None:
        self._status = SessionSnapshot(
            session_id=session_id,
            state=MappingState.IDLE,
            motion_allowed=False,
        )

    def snapshot(self) -> SessionSnapshot:
        return self._status

    def request(
        self,
        command: CommandType,
        *,
        preflight_ok: bool | None = None,
        has_initial_pose: bool = False,
    ) -> CommandResult:
        state = self._status.state
        if command is CommandType.START:
            if state not in (MappingState.IDLE, MappingState.ERROR_RECOVERABLE):
                return CommandResult(False, "start is only valid from IDLE or recoverable ERROR")
            if preflight_ok is not True:
                return CommandResult(False, "preflight must pass before start")
            self._status = self._replace(
                state=MappingState.STARTING,
                motion_allowed=False,
                ready=False,
                last_error="",
            )
            return CommandResult(True, "start accepted")
        if command is CommandType.PAUSE:
            if state is not MappingState.MAPPING:
                return CommandResult(False, "pause is only valid from MAPPING")
            self._status = self._replace(
                state=MappingState.PAUSED,
                motion_allowed=False,
            )
            return CommandResult(True, "pause accepted")
        if command is CommandType.RESUME:
            if state is not MappingState.PAUSED:
                return CommandResult(False, "resume is only valid from PAUSED")
            if preflight_ok is not True:
                return CommandResult(False, "preflight must pass before resume")
            self._status = self._replace(
                state=MappingState.STARTING,
                motion_allowed=False,
                ready=False,
                last_error="",
            )
            return CommandResult(True, "resume accepted")
        if command is CommandType.STOP:
            if state not in (MappingState.MAPPING, MappingState.PAUSED):
                return CommandResult(False, "stop is only valid while mapping or paused")
            self._status = self._replace(
                state=MappingState.SAVING,
                motion_allowed=False,
                ready=False,
            )
            return CommandResult(True, "stop accepted")
        if command is CommandType.SAVE:
            if state not in (MappingState.MAPPING, MappingState.PAUSED):
                return CommandResult(False, "save is only valid while mapping or paused")
            self._status = self._replace(
                state=MappingState.SAVING,
                motion_allowed=False,
                ready=False,
            )
            return CommandResult(True, "save accepted")
        if command is CommandType.LOAD:
            if state not in (
                MappingState.IDLE,
                MappingState.PAUSED,
                MappingState.ERROR_RECOVERABLE,
            ):
                return CommandResult(False, "load is only valid from IDLE, PAUSED, or recoverable ERROR")
            if not has_initial_pose:
                return CommandResult(False, "load requires an explicit initial pose")
            self._status = self._replace(state=MappingState.STARTING)
            return CommandResult(True, "load accepted")
        return CommandResult(False, "unknown mapping command")

    def mark_started(self) -> None:
        self._status = self._replace(
            state=MappingState.MAPPING,
            motion_allowed=True,
            ready=True,
        )

    def mark_paused(self) -> None:
        self._status = self._replace(
            state=MappingState.PAUSED,
            motion_allowed=False,
            ready=False,
        )

    def mark_resumed(self) -> None:
        self._status = self._replace(
            state=MappingState.MAPPING,
            motion_allowed=True,
            ready=True,
        )

    def mark_saved(self, *, resume: bool = False, revision: str | None = None) -> None:
        self._status = self._replace(
            state=MappingState.MAPPING if resume else MappingState.IDLE,
            motion_allowed=resume,
            ready=resume,
            current_revision=revision or self._status.current_revision,
        )

    def mark_failed(self, message: str) -> None:
        self._status = self._replace(
            state=MappingState.ERROR_RECOVERABLE,
            motion_allowed=False,
            ready=False,
            last_error=message,
        )

    def _replace(self, **changes: object) -> SessionSnapshot:
        return replace(self._status, **changes)
