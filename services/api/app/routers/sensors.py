from fastapi import APIRouter

from app.models.sensor import SensorSnapshot
from app.services.mock_data import make_sensor_snapshot

router = APIRouter(prefix="/sensors", tags=["sensors"])


@router.get("", response_model=SensorSnapshot)
def get_sensor_snapshot() -> SensorSnapshot:
    return make_sensor_snapshot()

