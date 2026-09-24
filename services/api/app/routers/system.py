from pathlib import Path

from fastapi import APIRouter, Request

from app.models.system import SystemSnapshot
from app.services.ros_runtime import RosRuntimeStore
from app.config import settings
from app.services.zone_store import ZoneStore
from app.state import MISSION_STATE, TASK_STATE, VOICE_STATE

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/snapshot", response_model=SystemSnapshot)
async def get_system_snapshot(request: Request) -> SystemSnapshot:
    runtime = getattr(request.app.state, "ros_runtime", None)
    if runtime is None:
        runtime = RosRuntimeStore(enabled=settings.ros_bridge_enabled)
        runtime.start()
        request.app.state.ros_runtime = runtime
    mapping_status = runtime.mapping_status()
    zone_store = getattr(request.app.state, "zone_store", None)
    if zone_store is None:
        zone_store = ZoneStore(Path(settings.mapping_session_dir) / "zones.json")
        request.app.state.zone_store = zone_store
        if hasattr(runtime, "update_zones"):
            runtime.update_zones(zone_store.list())
    return SystemSnapshot(
        map=runtime.map_snapshot(include_data=False),
        mapping=mapping_status,
        robot_pose=runtime.robot_pose(),
        zones=zone_store.list(),
        tasks=TASK_STATE,
        mission=runtime.mission_state() if hasattr(runtime, "mission_state") else MISSION_STATE,
        voice=VOICE_STATE,
        sensor=runtime.sensor_snapshot(),
    )
