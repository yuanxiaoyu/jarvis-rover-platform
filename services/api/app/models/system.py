from datetime import datetime

from pydantic import BaseModel

from app.models.map import MapModel
from app.models.mapping import MappingStatus
from app.models.mission import MissionState
from app.models.sensor import SensorSnapshot
from app.models.task import Task
from app.models.voice import VoiceSessionState
from app.models.zone import Zone


class RobotPoseState(BaseModel):
    available: bool = False
    frame_id: str = "map"
    x: float | None = None
    y: float | None = None
    yaw_rad: float | None = None
    linear_velocity_mps: float | None = None
    angular_velocity_radps: float | None = None
    timestamp: datetime | None = None
    error: str | None = None


class SystemSnapshot(BaseModel):
    map: MapModel
    mapping: MappingStatus
    robot_pose: RobotPoseState
    zones: list[Zone]
    tasks: list[Task]
    mission: MissionState
    voice: VoiceSessionState
    sensor: SensorSnapshot
