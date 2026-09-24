from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceConfig(BaseSettings):
    enabled: bool = Field(default=False, validation_alias="ROVER_VOICE_ENABLED")
    capture_device: str = Field(default="", validation_alias="ROVER_VOICE_CAPTURE_DEVICE")
    playback_device: str = Field(default="", validation_alias="ROVER_VOICE_PLAYBACK_DEVICE")
    wakeword_phrase: str = Field(default="贾维斯", min_length=1, max_length=64, validation_alias="ROVER_WAKEWORD_PHRASE")
    wakeword_model: str = Field(default="", validation_alias="ROVER_WAKEWORD_MODEL")
    wakeword_keywords_file: str = Field(default="", validation_alias="ROVER_WAKEWORD_KEYWORDS_FILE")
    wakeword_score: float = Field(default=2.0, gt=0, validation_alias="ROVER_WAKEWORD_SCORE")
    asr_model_dir: str = Field(default="", validation_alias="ROVER_ASR_MODEL_DIR")
    tts_model_dir: str = Field(default="", validation_alias="ROVER_TTS_MODEL_DIR")
    tts_engine: Literal["pocket_tts", "sherpa_vits"] = Field(default="pocket_tts", validation_alias="ROVER_TTS_ENGINE")
    tts_config: str = Field(default="", validation_alias="ROVER_TTS_CONFIG")
    tts_checkpoint: str = Field(default="", validation_alias="ROVER_TTS_CHECKPOINT")
    tts_voice_state: str = Field(default="", validation_alias="ROVER_TTS_VOICE_STATE")
    tts_device: str = Field(default="cpu", validation_alias="ROVER_TTS_DEVICE")
    tts_playback_sample_rate: int = Field(default=24000, gt=0, validation_alias="ROVER_TTS_PLAYBACK_SAMPLE_RATE")
    tts_speaker_id: int = Field(default=21, ge=0, validation_alias="ROVER_TTS_SPEAKER_ID")
    tts_rule_fsts: str = Field(default="", validation_alias="ROVER_TTS_RULE_FSTS")
    gateway_url: str = Field(default="http://127.0.0.1:8001/api/v1/voice", validation_alias="ROVER_VOICE_GATEWAY_URL")
    gateway_token: SecretStr | None = Field(default=None, validation_alias="ROVER_VOICE_GATEWAY_TOKEN")
    sample_rate: int = Field(default=16000, validation_alias="ROVER_VOICE_SAMPLE_RATE")
    channels: int = Field(default=1, validation_alias="ROVER_VOICE_CHANNELS")
    record_max_seconds: float = Field(default=15.0, gt=0, validation_alias="ROVER_VOICE_RECORD_MAX_SECONDS")
    followup_seconds: float = Field(default=8.0, gt=0, validation_alias="ROVER_VOICE_FOLLOWUP_SECONDS")
    wake_ack_text: str = Field(default="我在，请说。", max_length=200, validation_alias="ROVER_VOICE_WAKE_ACK_TEXT")
    vad_silence_ms: int = Field(default=700, gt=0, validation_alias="ROVER_VOICE_VAD_SILENCE_MS")
    wakeword_threshold: float = Field(default=0.5, ge=0, le=1, validation_alias="ROVER_WAKEWORD_THRESHOLD")
    wakeword_cooldown_seconds: float = Field(default=2.0, ge=0, validation_alias="ROVER_WAKEWORD_COOLDOWN_SECONDS")
    min_confidence: float = Field(default=0.35, ge=0, le=1, validation_alias="ROVER_VOICE_MIN_CONFIDENCE")
    max_audio_queue_frames: int = Field(default=750, ge=1, le=10000, validation_alias="ROVER_VOICE_MAX_AUDIO_QUEUE_FRAMES")
    heartbeat_interval_seconds: float = Field(default=3.0, gt=0, validation_alias="ROVER_VOICE_HEARTBEAT_INTERVAL_SECONDS")
    tts_max_audio_seconds: float = Field(default=60.0, gt=0, validation_alias="ROVER_TTS_MAX_AUDIO_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @field_validator("wakeword_phrase")
    @classmethod
    def validate_wakeword_phrase(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("wakeword phrase must be printable")
        return normalized

    def validate_prerequisites(self) -> None:
        if self.sample_rate != 16000 or self.channels != 1:
            raise ValueError("voice audio must be 16 kHz mono PCM16")
        if not self.enabled:
            return
        required = {
            "capture_device": self.capture_device,
            "playback_device": self.playback_device,
            "wakeword_model": self.wakeword_model,
            "asr_model_dir": self.asr_model_dir,
            "tts_model_dir": self.tts_model_dir,
            "gateway_token": self.gateway_token.get_secret_value() if self.gateway_token else "",
        }
        if self.tts_engine == "pocket_tts":
            required.update({
                "tts_checkpoint": self.tts_checkpoint,
                "tts_voice_state": self.tts_voice_state,
            })
        for name, value in required.items():
            if not value:
                raise ValueError(f"{name} is required when voice is enabled")
        parsed = urlsplit(self.gateway_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
            raise ValueError("voice gateway must use loopback HTTP")
        wakeword_path = Path(self.wakeword_model)
        if not wakeword_path.is_file() and not wakeword_path.is_dir():
            raise ValueError("wakeword model file or directory does not exist")
        if wakeword_path.is_dir():
            required_kws_files = (
                wakeword_path / "tokens.txt",
                *tuple(sorted(wakeword_path.glob("*encoder*.onnx")))[:1],
                *tuple(sorted(wakeword_path.glob("*decoder*.onnx")))[:1],
                *tuple(sorted(wakeword_path.glob("*joiner*.onnx")))[:1],
            )
            if any(not path.is_file() for path in required_kws_files):
                raise ValueError("sherpa-onnx KWS model directory is incomplete")
            if not any(path.is_file() for path in (
                wakeword_path / "keywords.txt",
                wakeword_path / "test_wavs" / "keywords.txt",
            )):
                raise ValueError("sherpa-onnx KWS keywords.txt is missing")
        if self.wakeword_keywords_file and not Path(self.wakeword_keywords_file).is_file():
            raise ValueError("configured wakeword keywords file does not exist")
        asr_path = Path(self.asr_model_dir)
        if not asr_path.is_dir():
            raise ValueError("ASR model directory does not exist")
        if not (asr_path / "tokens.txt").is_file() or any(
            not any(asr_path.glob(pattern)) for pattern in ("*encoder*.onnx", "*decoder*.onnx", "*joiner*.onnx")
        ):
            raise ValueError("ASR model directory is incomplete")
        tts_path = Path(self.tts_model_dir)
        if not tts_path.is_dir():
            raise ValueError(f"{self.tts_engine} model directory does not exist")
        if self.tts_engine == "pocket_tts":
            config_path = Path(self.tts_config) if self.tts_config else tts_path / "config.yaml"
            if not config_path.is_file():
                raise ValueError("Pocket TTS local config does not exist")
            try:
                config_text = config_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise ValueError("Pocket TTS local config is not readable") from exc
            if re.search(r"(?:^|\s)(?:hf|https?)://", config_text):
                raise ValueError("Pocket TTS local config contains a remote asset")
            if not Path(self.tts_checkpoint).is_file():
                raise ValueError("Pocket TTS checkpoint does not exist")
            if not Path(self.tts_voice_state).is_file():
                raise ValueError("Pocket TTS voice state does not exist")
        elif self.tts_engine == "sherpa_vits":
            for name in ("model.onnx", "lexicon.txt", "tokens.txt"):
                if not (tts_path / name).is_file():
                    raise ValueError(f"sherpa VITS model file is missing: {name}")
        from .audio import probe_capture_device, probe_playback_device

        capture_ok, capture_reason = probe_capture_device(self.capture_device)
        if not capture_ok:
            raise ValueError(capture_reason)
        playback_ok, playback_reason = probe_playback_device(self.playback_device)
        if not playback_ok:
            raise ValueError(playback_reason)


def load_config() -> VoiceConfig:
    return VoiceConfig()
