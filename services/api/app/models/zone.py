from enum import Enum

from pydantic import BaseModel, Field

from app.models.map import Coordinate2D


class ZoneType(str, Enum):
    KEEP_OUT = "keepout"
    VIRTUAL_WALL = "virtual_wall"
    SLOW = "slow"
    SEMANTIC = "semantic"


class Zone(BaseModel):
    zone_id: str
    name: str
    type: ZoneType
    points: list[Coordinate2D] = Field(default_factory=list, min_length=2)
    nav2_keepout_enabled: bool = True
    nav2_virtual_wall_enabled: bool = False
    semantic_label: str | None = None
    extrusion_height_m: float = Field(default=1.2, ge=0.0)

