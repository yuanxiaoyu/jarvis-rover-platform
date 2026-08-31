import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_Identifier = Field(
    min_length=1,
    max_length=64,
    pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
)


class _AssistantModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MappingAction(_AssistantModel):
    type: Literal[
        "mapping_start",
        "mapping_pause",
        "mapping_resume",
        "mapping_save",
        "mapping_stop",
    ]
    map_name: str | None = Field(default=None, max_length=64)

    @field_validator("map_name")
    @classmethod
    def validate_map_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value.strip() != value or ".." in value:
            raise ValueError("map_name contains an invalid path component")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("map_name cannot contain control characters")
        if "/" in value or "\\" in value:
            raise ValueError("map_name cannot contain path separators")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
            raise ValueError("map_name contains unsupported characters")
        return value

    @model_validator(mode="after")
    def validate_action_name(self) -> "MappingAction":
        if self.type == "mapping_save" and not self.map_name:
            raise ValueError("map_name is required for mapping_save")
        if self.type != "mapping_save" and self.map_name is not None:
            raise ValueError("map_name is only valid for mapping_save")
        return self


class AssistantDecision(_AssistantModel):
    reply_text: str = Field(min_length=1, max_length=2000)
    action: MappingAction | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("reply_text")
    @classmethod
    def validate_reply_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reply_text must not be blank")
        return value


class VoiceAssistantRequest(_AssistantModel):
    schema_version: Literal[1] = 1
    session_id: str = _Identifier
    turn_id: str = _Identifier
    transcript: str = Field(min_length=1, max_length=1000)
    language: str = Field(default="zh-CN", min_length=1, max_length=32)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: Literal["local-sherpa-onnx"] = "local-sherpa-onnx"

    @field_validator("transcript")
    @classmethod
    def validate_transcript(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 and char not in "\t" for char in value):
            raise ValueError("transcript must be non-empty and printable")
        return value


class AssistantError(_AssistantModel):
    code: Literal[
        "assistant_unavailable",
        "command_rejected",
        "invalid_decision",
        "voice_unauthorized",
    ]
    message: str = Field(min_length=1, max_length=500)
    recoverable: bool

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class VoiceAssistantResponse(_AssistantModel):
    schema_version: Literal[1] = 1
    session_id: str = _Identifier
    turn_id: str = _Identifier
    state: Literal[
        "completed",
        "awaiting_confirmation",
        "executed",
        "rejected",
        "unavailable",
    ]
    reply_text: str = Field(min_length=1, max_length=2000)
    action: MappingAction | None = None
    error: AssistantError | None = None

    @field_validator("reply_text")
    @classmethod
    def validate_reply_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reply_text must not be blank")
        return value


class VoiceStatus(_AssistantModel):
    state: Literal[
        "disabled",
        "wake_listening",
        "capturing",
        "processing_asr",
        "processing_assistant",
        "speaking",
        "audio_unavailable",
        "asr_error",
        "assistant_unavailable",
        "tts_error",
    ]
    enabled: bool
    session_id: str | None = None
    turn_id: str | None = None
    last_error: AssistantError | None = None
    component_latency_ms: dict[str, float | None] = Field(default_factory=dict)

    @field_validator("session_id", "turn_id")
    @classmethod
    def validate_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
            raise ValueError("identifier contains unsupported characters")
        return value

    @field_validator("component_latency_ms")
    @classmethod
    def validate_latencies(cls, value: dict[str, float | None]) -> dict[str, float | None]:
        if any(latency is not None and latency < 0 for latency in value.values()):
            raise ValueError("component latency cannot be negative")
        return value
