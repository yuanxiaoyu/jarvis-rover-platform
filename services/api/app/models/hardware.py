from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class RadarPoint(BaseModel):
    angle_rad: float
    range_m: float = Field(ge=0.0)
    x_m: float
    y_m: float
    intensity: float | None = Field(default=None, ge=0.0)


class RadarScan(BaseModel):
    source: Literal["ms200_tof_2d"] = "ms200_tof_2d"
    available: bool = False
    frame_id: str = "laser_frame"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    angle_min_rad: float = 0.0
    angle_max_rad: float = 0.0
    range_min_m: float = 0.0
    range_max_m: float = 0.0
    points: list[RadarPoint] = Field(default_factory=list)
    error: str | None = None


class GimbalState(BaseModel):
    available: bool = False
    pan_deg: float | None = None
    tilt_deg: float | None = None
    pan_topic: str = "/servo_s1"
    tilt_topic: str = "/servo_s2"
    error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GimbalCommand(BaseModel):
    pan_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    tilt_deg: float | None = Field(default=None, ge=-90.0, le=20.0)

    def has_axis(self) -> bool:
        return self.pan_deg is not None or self.tilt_deg is not None
