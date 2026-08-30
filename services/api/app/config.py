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

    model_config = SettingsConfigDict(env_prefix="ROVER_", env_file=".env", extra="ignore")


settings = Settings()
