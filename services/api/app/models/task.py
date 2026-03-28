from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.models.map import Coordinate2D


class TaskType(str, Enum):
    NAVIGATE = "navigate"
    PATROL = "patrol"
    INSPECT = "inspect"
    RETURN_TO_DOCK = "return_to_dock"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    task_id: str
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    target: Coordinate2D | None = None
    description: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskCreate(BaseModel):
    type: TaskType
    target: Coordinate2D | None = None
    description: str = ""


class TaskStatusPatch(BaseModel):
    status: TaskStatus

