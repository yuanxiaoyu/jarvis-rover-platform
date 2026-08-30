from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MappingState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    MAPPING = "mapping"
    PAUSED = "paused"
    SAVING = "saving"
    ERROR_RECOVERABLE = "error_recoverable"


class MappingStatus(BaseModel):
    session_id: str | None = None
    state: MappingState = MappingState.IDLE
    ready: bool = False
    motion_allowed: bool = False
    map_update_age_s: float | None = None
    current_revision: str | None = None
    last_error: str = ""


class MappingCommandResult(BaseModel):
    accepted: bool
    state: MappingState
    message: str


class SessionRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class SaveRequest(BaseModel):
    map_name: str = Field(default="map", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class PoseRequest(SessionRequest):
    map_name: str = Field(default="map", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    x: float
    y: float
    yaw: float
    match_type: Literal[2, 3] = 2
