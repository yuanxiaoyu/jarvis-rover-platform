from fastapi import APIRouter, Request

from app.config import settings
from app.models.sensor import SensorSnapshot
from app.services.ros_runtime import RosRuntimeStore

router = APIRouter(prefix="/sensors", tags=["sensors"])


@router.get("", response_model=SensorSnapshot)
def get_sensor_snapshot(request: Request) -> SensorSnapshot:
    runtime = getattr(request.app.state, "ros_runtime", None)
    if runtime is None:
        runtime = RosRuntimeStore(enabled=settings.ros_bridge_enabled)
        runtime.start()
        request.app.state.ros_runtime = runtime
    return runtime.sensor_snapshot()
