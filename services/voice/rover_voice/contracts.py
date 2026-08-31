from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class VoiceRuntime:
    state: VoiceState = VoiceState.DISABLED
    session_id: str | None = None
    turn_id: str | None = None
    last_error: str | None = None


class AudioInput(Protocol):
    def start(self) -> AsyncIterator[bytes]: ...
    async def close(self) -> None: ...


class AudioOutput(Protocol):
    def play_pcm(self, stream: AsyncIterator[bytes], stop_event) -> None: ...
    async def close(self) -> None: ...


class WakeWordDetector(Protocol):
    def process(self, frame: bytes) -> bool: ...


class SpeechRecognizer(Protocol):
    def transcribe(self, frames: list[bytes]) -> AsrResult: ...
    def is_speech(self, frame: bytes) -> bool: ...


class TtsPlayer(Protocol):
    def speak(self, text: str, stop_event) -> None: ...
