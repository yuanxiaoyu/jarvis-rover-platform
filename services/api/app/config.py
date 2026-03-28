from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_name: str = "Rover API"
    api_version: str = "0.1.0"
    telemetry_interval_seconds: float = 1.0
    api_cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(env_prefix="ROVER_", env_file=".env", extra="ignore")


settings = Settings()
