from fastapi import APIRouter, HTTPException

from app.models.zone import Zone
from app.state import ZONE_STATE

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("", response_model=list[Zone])
def list_zones() -> list[Zone]:
    return ZONE_STATE


@router.post("", response_model=Zone)
def create_zone(zone: Zone) -> Zone:
    if any(existing.zone_id == zone.zone_id for existing in ZONE_STATE):
        raise HTTPException(status_code=409, detail="zone_id already exists")
    ZONE_STATE.append(zone)
    return zone


@router.delete("/{zone_id}", response_model=dict[str, str])
def delete_zone(zone_id: str) -> dict[str, str]:
    for index, zone in enumerate(ZONE_STATE):
        if zone.zone_id == zone_id:
            ZONE_STATE.pop(index)
            return {"deleted": zone_id}
    raise HTTPException(status_code=404, detail="zone not found")

