from pydantic import BaseModel

from app.models.map import MapModel
from app.models.mission import MissionState
from app.models.sensor import SensorSnapshot
from app.models.task import Task
from app.models.voice import VoiceSessionState
from app.models.zone import Zone


class SystemSnapshot(BaseModel):
    map: MapModel
    zones: list[Zone]
    tasks: list[Task]
    mission: MissionState
    voice: VoiceSessionState
    sensor: SensorSnapshot
