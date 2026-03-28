from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MapSource(str, Enum):
    MS200_TOF_2D = "ms200_tof_2d"


class Coordinate2D(BaseModel):
    x: float
    y: float


class GridOrigin(BaseModel):
    x: float = 0.0
    y: float = 0.0
    yaw_rad: float = 0.0


class OccupancyGridMeta(BaseModel):
    resolution_m_per_cell: float = Field(default=0.05, gt=0.0)
    width_cells: int = Field(default=200, ge=1)
    height_cells: int = Field(default=200, ge=1)
    origin: GridOrigin = Field(default_factory=GridOrigin)
    frame_id: str = "map"


class Reconstructed3DLayer(BaseModel):
    layer_id: str
    method: Literal["extruded_occupancy", "zone_mesh_overlay"]
    description: str
    source_zone_ids: list[str] = Field(default_factory=list)
    height_m: float = Field(default=1.2, ge=0.0)


class MapModel(BaseModel):
    map_id: str = "default_map"
    name: str = "Rover Demo Map"
    source: MapSource = MapSource.MS200_TOF_2D
    occupancy: OccupancyGridMeta = Field(default_factory=OccupancyGridMeta)
    reconstruction_3d_enabled: bool = True
    reconstruction_layers: list[Reconstructed3DLayer] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

