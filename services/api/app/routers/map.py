from datetime import datetime, timezone

from fastapi import APIRouter

from app.models.map import MapModel
from app.state import MAP_STATE

router = APIRouter(prefix="/map", tags=["map"])


@router.get("", response_model=MapModel)
def get_map() -> MapModel:
    return MAP_STATE


@router.put("", response_model=MapModel)
def update_map(map_payload: MapModel) -> MapModel:
    map_payload.updated_at = datetime.now(timezone.utc)
    MAP_STATE.map_id = map_payload.map_id
    MAP_STATE.name = map_payload.name
    MAP_STATE.source = map_payload.source
    MAP_STATE.occupancy = map_payload.occupancy
    MAP_STATE.reconstruction_3d_enabled = map_payload.reconstruction_3d_enabled
    MAP_STATE.reconstruction_layers = map_payload.reconstruction_layers
    MAP_STATE.updated_at = map_payload.updated_at
    return MAP_STATE

