from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_name: str = "Rover API"
    api_version: str = "0.1.0"
    telemetry_interval_seconds: float = 1.0
    api_cors_origins: list[str] = ["*"]
    ros_bridge_enabled: bool = False
    ros_bridge_required: bool = False
    ros_service_timeout_seconds: float = 10.0
    ros_status_timeout_seconds: float = 2.0
    ros_status_topic: str = "/mapping/status"
    ros_command_service: str = "/mapping/command"
    mapping_session_dir: str = "/workspace/data/maps"

    # Assistant configuration is disabled by default until a protected key is provisioned.
    ai_enabled: bool = False
    ai_base_url: str = "https://gmn.chuangzuoli.com/v1"
    ai_model: str = "gpt-5.6"
    ai_wire_api: str = "chat_completions"
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=20.0, gt=0)
    ai_max_output_tokens: int = Field(default=512, ge=1)
    voice_gateway_token: SecretStr | None = None
    voice_transcript_max_chars: int = Field(default=1000, ge=1)
    voice_confirmation_ttl_seconds: float = Field(default=15.0, gt=0)
    voice_followup_seconds: float = Field(default=8.0, gt=0)
    voice_status_stale_seconds: float = Field(default=15.0, gt=0)

    model_config = SettingsConfigDict(env_prefix="ROVER_", env_file=".env", extra="ignore")

    def validate_assistant_configuration(self) -> None:
        """Validate settings required when the remote assistant is enabled."""
        if not self.ai_enabled:
            return
        if not self.ai_api_key:
            raise ValueError("ROVER_AI_API_KEY is required when ROVER_AI_ENABLED=true")
        if self.voice_gateway_token and self.ai_api_key.get_secret_value() == self.voice_gateway_token.get_secret_value():
            raise ValueError("ROVER_AI_API_KEY and ROVER_VOICE_GATEWAY_TOKEN must be different")
        if not self.ai_base_url.startswith(("http://", "https://")):
            raise ValueError("ROVER_AI_BASE_URL must use http or https")
        if self.ai_timeout_seconds <= 0 or self.ai_max_output_tokens < 1:
            raise ValueError("assistant timeout and output limit must be positive")


settings = Settings()
