from pydantic import SecretStr
import pytest

from app.config import Settings


def test_enabled_assistant_requires_api_key():
    settings = Settings(ai_enabled=True, ai_api_key=None, voice_gateway_token=SecretStr("voice-token"))
    with pytest.raises(ValueError, match="ROVER_AI_API_KEY"):
        settings.validate_assistant_configuration()


def test_assistant_and_voice_secrets_must_differ():
    settings = Settings(
        ai_enabled=False,
        ai_api_key=SecretStr("same-secret"),
        voice_gateway_token=SecretStr("same-secret"),
    )
    with pytest.raises(ValueError, match="must be different"):
        settings.validate_assistant_configuration()


def test_enabled_assistant_rejects_invalid_base_url():
    settings = Settings(
        ai_enabled=True,
        ai_api_key=SecretStr("api-secret"),
        voice_gateway_token=SecretStr("voice-secret"),
        ai_base_url="not-a-url",
    )
    with pytest.raises(ValueError, match="ROVER_AI_BASE_URL"):
        settings.validate_assistant_configuration()


def test_secret_values_do_not_appear_in_settings_repr():
    settings = Settings(ai_api_key=SecretStr("api-secret"), voice_gateway_token=SecretStr("voice-secret"))
    rendered = repr(settings)
    assert "api-secret" not in rendered
    assert "voice-secret" not in rendered
