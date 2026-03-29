from enum import Enum

from pydantic import BaseModel, Field


class MissionMode(str, Enum):
    IDLE = "idle"
    AUTONOMY = "autonomy"
    MANUAL = "manual"
    PAUSED = "paused"
    RETURNING = "returning"


class MissionState(BaseModel):
    mode: MissionMode = MissionMode.IDLE
    objective: str = "等待任务"
    status_line: str = "待命"
    selected_zone_id: str | None = None


class NavigateRequest(BaseModel):
    zone_id: str


class AiCommandRequest(BaseModel):
    prompt: str = Field(min_length=1)


class WholeHomeGarbageScanRequest(BaseModel):
    transcript: str = "贾维斯，请帮我扫描整个房屋，发现有垃圾请拍照告诉我。"
    report_channel: str = "openclaw"
    report_target: str = "feishu"
    require_photo: bool = True
