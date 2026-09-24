from app.models.map import MapModel
from app.models.mission import MissionState
from app.models.task import Task
from app.models.voice import VoiceSessionState
from app.models.zone import Zone

MAP_STATE = MapModel()
ZONE_STATE: list[Zone] = []
TASK_STATE: list[Task] = []
MISSION_STATE = MissionState()
VOICE_STATE = VoiceSessionState(
    listening=False,
    adapter="host_gateway_passive",
    transcript="语音服务状态见 /api/v1/voice/status",
)
