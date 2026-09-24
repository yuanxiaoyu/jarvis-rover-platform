from datetime import datetime, timezone

from pydantic import BaseModel, Field


class VoiceCommand(BaseModel):
    transcript: str = Field(min_length=1)
    intent: str = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    language: str = "en-US"
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VoiceAck(BaseModel):
    accepted: bool
    message: str
    intent: str
    adapter: str = "host_gateway_passive"


class VoiceSessionState(BaseModel):
    """Legacy snapshot shape; it reports passive/unavailable status only."""

    listening: bool = False
    wake_word: str = "贾维斯"
    adapter: str = "host_gateway_passive"
    transcript: str = "语音服务状态见 /api/v1/voice/status"
