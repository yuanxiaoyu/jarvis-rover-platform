from enum import Enum

import math

from pydantic import BaseModel, Field, model_validator

from app.models.map import Coordinate2D


class ZoneType(str, Enum):
    KEEP_OUT = "keepout"
    VIRTUAL_WALL = "virtual_wall"
    SLOW = "slow"
    SEMANTIC = "semantic"


class Zone(BaseModel):
    zone_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str = Field(min_length=1, max_length=64)
    type: ZoneType
    points: list[Coordinate2D] = Field(default_factory=list, min_length=2)
    nav2_keepout_enabled: bool = True
    nav2_virtual_wall_enabled: bool = False
    semantic_label: str | None = None
    extrusion_height_m: float = Field(default=1.2, ge=0.0)

    @model_validator(mode="after")
    def validate_geometry(self) -> "Zone":
        minimum = 2 if self.type is ZoneType.VIRTUAL_WALL else 3
        if len(self.points) < minimum:
            raise ValueError(f"{self.type.value} requires at least {minimum} points")
        if any(not math.isfinite(point.x) or not math.isfinite(point.y) for point in self.points):
            raise ValueError("zone coordinates must be finite")
        if self.type is not ZoneType.VIRTUAL_WALL:
            area_twice = sum(
                first.x * second.y - second.x * first.y
                for first, second in zip(self.points, [*self.points[1:], self.points[0]])
            )
            if abs(area_twice) < 1e-6:
                raise ValueError("zone polygon must enclose a non-zero area")
        return self
