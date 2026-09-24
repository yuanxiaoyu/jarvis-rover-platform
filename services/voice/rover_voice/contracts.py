from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Protocol


class VoiceState(str, Enum):
    DISABLED = "disabled"
    WAKE_LISTENING = "wake_listening"
    CAPTURING = "capturing"
    PROCESSING_ASR = "processing_asr"
    PROCESSING_ASSISTANT = "processing_assistant"
    SPEAKING = "speaking"
    AUDIO_UNAVAILABLE = "audio_unavailable"
    ASR_ERROR = "asr_error"
    ASSISTANT_UNAVAILABLE = "assistant_unavailable"
    TTS_ERROR = "tts_error"


@dataclass(frozen=True)
class AsrResult:
    text: str
    confidence: float | None
    duration_ms: int


@dataclass(frozen=True)
class VoiceAssistantRequest:
    session_id: str
    turn_id: str
    transcript: str
    language: str = "zh-CN"
    confidence: float | None = None
    schema_version: int = 1
    source: str = "local-sherpa-onnx"

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "transcript": self.transcript,
            "language": self.language,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass(frozen=True)
class VoiceStatus:
    state: VoiceState
    enabled: bool
    session_id: str | None = None
    turn_id: str | None = None
    last_error: dict[str, object] | None = None
    component_latency_ms: dict[str, float | None] = field(default_factory=dict)

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        return {
            "schema_version": 1,
            "state": self.state.value,
            "enabled": self.enabled,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "last_error": self.last_error,
            "component_latency_ms": self.component_latency_ms,
        }


@dataclass
class VoiceRuntime:
    state: VoiceState = VoiceState.DISABLED
    session_id: str | None = None
    turn_id: str | None = None
    last_error: dict[str, object] | None = None
    state_changed_at: float = 0.0


class AudioInput(Protocol):
    def start(self) -> AsyncIterator[bytes]: ...
    async def close(self) -> None: ...


class WakeWordDetector(Protocol):
    def process(self, frame: bytes) -> bool: ...


class SpeechRecognizer(Protocol):
    def transcribe(self, frames: list[bytes]) -> AsrResult: ...
    def is_speech(self, frame: bytes) -> bool: ...


class TtsPlayer(Protocol):
    def speak(self, text: str, stop_event) -> None: ...


class GatewayClientProtocol(Protocol):
    async def assistant(self, request: VoiceAssistantRequest): ...
    async def heartbeat(self, status: VoiceStatus) -> None: ...
    async def close(self) -> None: ...
