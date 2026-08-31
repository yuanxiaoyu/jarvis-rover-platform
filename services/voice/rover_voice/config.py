from __future__ import annotations

import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceConfig(BaseSettings):
    enabled: bool = Field(default=False, validation_alias="ROVER_VOICE_ENABLED")
    capture_device: str = Field(default="", validation_alias="ROVER_VOICE_CAPTURE_DEVICE")
    playback_device: str = Field(default="", validation_alias="ROVER_VOICE_PLAYBACK_DEVICE")
    wakeword_model: str = Field(default="", validation_alias="ROVER_WAKEWORD_MODEL")
    asr_model_dir: str = Field(default="", validation_alias="ROVER_ASR_MODEL_DIR")
    tts_model: str = Field(default="", validation_alias="ROVER_TTS_MODEL")
    tts_config: str = Field(default="", validation_alias="ROVER_TTS_CONFIG")
    gateway_url: str = Field(default="http://127.0.0.1:8000/api/v1/voice", validation_alias="ROVER_VOICE_GATEWAY_URL")
    gateway_token: str = Field(default="", validation_alias="ROVER_VOICE_GATEWAY_TOKEN")
    sample_rate: int = Field(default=16000, validation_alias="ROVER_VOICE_SAMPLE_RATE")
    channels: int = Field(default=1, validation_alias="ROVER_VOICE_CHANNELS")
    record_max_seconds: float = Field(default=15.0, gt=0, validation_alias="ROVER_VOICE_RECORD_MAX_SECONDS")
    followup_seconds: float = Field(default=8.0, gt=0, validation_alias="ROVER_VOICE_FOLLOWUP_SECONDS")
    vad_silence_ms: int = Field(default=700, gt=0, validation_alias="ROVER_VOICE_VAD_SILENCE_MS")
    wakeword_threshold: float = Field(default=0.5, ge=0, le=1, validation_alias="ROVER_WAKEWORD_THRESHOLD")
    wakeword_cooldown_seconds: float = Field(default=2.0, ge=0, validation_alias="ROVER_WAKEWORD_COOLDOWN_SECONDS")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    def validate_prerequisites(self) -> None:
        if self.sample_rate != 16000 or self.channels != 1:
            raise ValueError("voice audio must be 16 kHz mono PCM16")
        if not self.enabled:
            return
        for name in ("capture_device", "playback_device", "wakeword_model", "asr_model_dir", "tts_model", "tts_config", "gateway_token"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required when voice is enabled")
        if not self.gateway_url.startswith("http://127.0.0.1") and not self.gateway_url.startswith("http://[::1]"):
            raise ValueError("voice gateway must use loopback HTTP")
        for path_name in ("wakeword_model", "asr_model_dir", "tts_model", "tts_config"):
            if not Path(getattr(self, path_name)).exists():
                raise ValueError(f"model path does not exist: {path_name}")


def load_config() -> VoiceConfig:
    return VoiceConfig()
