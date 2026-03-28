from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.map import Coordinate2D
from app.models.sensor import SensorSnapshot


class TelemetryPacket(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pose: Coordinate2D
    speed_mps: float = 0.0
    active_task_id: str | None = None
    sensor: SensorSnapshot

