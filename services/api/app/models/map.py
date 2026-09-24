from datetime import datetime, timezone
from enum import Enum
from typing import Literal

import math

from pydantic import BaseModel, Field, field_validator, model_validator


class MapSource(str, Enum):
    UNKNOWN = "unknown"
    MS200_TOF_2D = "ms200_tof_2d"


class Coordinate2D(BaseModel):
    x: float
    y: float

    @field_validator("x", "y")
    @classmethod
    def finite_coordinate(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coordinate values must be finite")
        return value


class GridOrigin(BaseModel):
    x: float = 0.0
    y: float = 0.0
    yaw_rad: float = 0.0


class OccupancyGridMeta(BaseModel):
    resolution_m_per_cell: float = Field(default=0.05, gt=0.0)
    width_cells: int = Field(default=0, ge=0)
    height_cells: int = Field(default=0, ge=0)
    origin: GridOrigin = Field(default_factory=GridOrigin)
    frame_id: str = "map"
    data: list[int] | None = None

    @model_validator(mode="after")
    def validate_grid(self) -> "OccupancyGridMeta":
        if self.data is not None:
            if self.width_cells < 1 or self.height_cells < 1:
                raise ValueError("occupancy dimensions must be positive when grid data is present")
            if len(self.data) != self.width_cells * self.height_cells:
                raise ValueError("occupancy data length does not match map dimensions")
            if any(cell < -1 or cell > 100 for cell in self.data):
                raise ValueError("occupancy values must be between -1 and 100")
        return self


class Reconstructed3DLayer(BaseModel):
    layer_id: str
    method: Literal["extruded_occupancy", "zone_mesh_overlay"]
    description: str
    source_zone_ids: list[str] = Field(default_factory=list)
    height_m: float = Field(default=1.2, ge=0.0)


class MapModel(BaseModel):
    map_id: str = ""
    name: str = "未加载地图"
    source: MapSource = MapSource.UNKNOWN
    occupancy: OccupancyGridMeta = Field(default_factory=OccupancyGridMeta)
    available: bool = False
    reconstruction_3d_enabled: bool = True
    reconstruction_layers: list[Reconstructed3DLayer] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
