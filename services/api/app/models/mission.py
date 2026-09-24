from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.map import Coordinate2D


class MissionMode(str, Enum):
    IDLE = "idle"
    AUTONOMY = "autonomy"
    MANUAL = "manual"
    PAUSED = "paused"
    RETURNING = "returning"


class MissionState(BaseModel):
    mode: MissionMode = MissionMode.IDLE
    objective: str = "等待任务"
    status_line: str = "待命"
    selected_zone_id: str | None = None
    exploration_state: Literal["idle", "starting", "exploring", "paused", "complete", "stopped", "error"] = "idle"
    exploration_message: str = "待命"
    current_target: Coordinate2D | None = None
    completed_frontiers: int = Field(default=0, ge=0)
    failed_frontiers: int = Field(default=0, ge=0)
    remaining_frontiers: int = Field(default=0, ge=0)


class NavigateRequest(BaseModel):
    zone_id: str


class PathPlanRequest(BaseModel):
    goal: Coordinate2D | None = None
    zone_id: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "PathPlanRequest":
        if (self.goal is None) == (self.zone_id is None):
            raise ValueError("provide exactly one of goal or zone_id")
        return self


class PathPlanResponse(BaseModel):
    available: bool = True
    waypoints: list[Coordinate2D]
    length_m: float
    explored_cells: int
    goal_reached: Coordinate2D
    message: str = ""


class AiCommandRequest(BaseModel):
    prompt: str = Field(min_length=1)
