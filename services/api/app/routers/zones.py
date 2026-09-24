from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.models.zone import Zone
from app.services.zone_store import ZoneStore

router = APIRouter(prefix="/zones", tags=["zones"])


def _store(request: Request) -> ZoneStore:
    store = getattr(request.app.state, "zone_store", None)
    if store is None:
        store = ZoneStore(Path(settings.mapping_session_dir) / "zones.json")
        request.app.state.zone_store = store
    return store


def _sync_navigation_zones(request: Request) -> None:
    runtime = getattr(request.app.state, "ros_runtime", None)
    if runtime is not None and hasattr(runtime, "update_zones"):
        runtime.update_zones(_store(request).list())


@router.get("", response_model=list[Zone])
def list_zones(request: Request) -> list[Zone]:
    return _store(request).list()


@router.post("", response_model=Zone)
def create_zone(request: Request, zone: Zone) -> Zone:
    try:
        result = _store(request).create(zone)
        _sync_navigation_zones(request)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/{zone_id}", response_model=Zone)
def update_zone(request: Request, zone_id: str, zone: Zone) -> Zone:
    try:
        updated = _store(request).update(zone_id, zone)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="zone not found")
    _sync_navigation_zones(request)
    return updated


@router.delete("/{zone_id}", response_model=dict[str, str])
def delete_zone(request: Request, zone_id: str) -> dict[str, str]:
    if not _store(request).delete(zone_id):
        raise HTTPException(status_code=404, detail="zone not found")
    _sync_navigation_zones(request)
    return {"deleted": zone_id}
