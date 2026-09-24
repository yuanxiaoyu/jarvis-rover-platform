from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    api_name: str = "Rover API"
    api_version: str = "0.1.0"
    telemetry_interval_seconds: float = 1.0
    api_cors_origins: list[str] = ["*"]

    # ROS remains optional so API startup is independent of the voice service.
    ros_bridge_enabled: bool = True
    ros_bridge_required: bool = False
    ros_service_timeout_seconds: float = Field(default=10.0, gt=0)
    ros_status_timeout_seconds: float = Field(default=2.0, gt=0)
    ros_status_topic: str = "/mapping/status"
    ros_command_service: str = "/mapping/command"
    mapping_session_dir: str = "/workspace/data/maps"
    ros_mapping_launch_command: list[str] = ["ros2", "launch", "rover_bringup", "mapping.launch.py"]
    camera_device: str = "/dev/video0"
    camera_width: int = Field(default=1280, ge=160, le=3840)
    camera_height: int = Field(default=720, ge=120, le=2160)
    camera_fps: int = Field(default=60, ge=1, le=120)
    gimbal_pan_topic: str = "/servo_s1"
    gimbal_tilt_topic: str = "/servo_s2"
    gimbal_pan_min_deg: float = -90.0
    gimbal_pan_max_deg: float = 90.0
    gimbal_tilt_min_deg: float = -90.0
    gimbal_tilt_max_deg: float = 20.0

    # Assistant configuration is disabled until a protected key is provisioned.
    ai_enabled: bool = False
    ai_base_url: str = "https://totokens.cc/v1"
    ai_model: str = "gpt-5.6-sol"
    ai_wire_api: str = "chat_completions"
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=20.0, gt=0)
    ai_max_output_tokens: int = Field(default=512, ge=1, le=4096)
    voice_gateway_token: SecretStr | None = None
    voice_transcript_max_chars: int = Field(default=1000, ge=1, le=10000)
    voice_confirmation_ttl_seconds: float = Field(default=15.0, gt=0)
    voice_followup_seconds: float = Field(default=8.0, gt=0)
    voice_status_stale_seconds: float = Field(default=15.0, gt=0)

    model_config = SettingsConfigDict(
        env_prefix="ROVER_",
        # Resolve the repository-level file regardless of whether uvicorn is
        # launched from the repository root or from services/api.
        env_file=(PROJECT_ENV_FILE, ".env"),
        extra="ignore",
        populate_by_name=True,
    )

    def validate_assistant_configuration(self) -> None:
        """Validate settings required when the remote assistant is enabled."""
        if self.ai_api_key and self.voice_gateway_token:
            if self.ai_api_key.get_secret_value() == self.voice_gateway_token.get_secret_value():
                raise ValueError("ROVER_AI_API_KEY and ROVER_VOICE_GATEWAY_TOKEN must be different")
        if not self.ai_enabled:
            return
        if not self.ai_api_key or not self.ai_api_key.get_secret_value():
            raise ValueError("ROVER_AI_API_KEY is required when ROVER_AI_ENABLED=true")
        parsed = urlsplit(self.ai_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ROVER_AI_BASE_URL must use http or https")
        if self.ai_wire_api not in {"chat_completions", "responses"}:
            raise ValueError("ROVER_AI_WIRE_API must be chat_completions or responses")
        if self.ai_timeout_seconds <= 0 or self.ai_max_output_tokens < 1:
            raise ValueError("assistant timeout and output limit must be positive")


settings = Settings()
