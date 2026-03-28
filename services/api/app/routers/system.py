from fastapi import APIRouter

from app.models.system import SystemSnapshot
from app.services.mock_data import make_sensor_snapshot
from app.state import MAP_STATE, MISSION_STATE, TASK_STATE, VOICE_STATE, ZONE_STATE

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/snapshot", response_model=SystemSnapshot)
def get_system_snapshot() -> SystemSnapshot:
    return SystemSnapshot(
        map=MAP_STATE,
        zones=ZONE_STATE,
        tasks=TASK_STATE,
        mission=MISSION_STATE,
        voice=VOICE_STATE,
        sensor=make_sensor_snapshot(),
    )
