import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.models.assistant import (
    AssistantDecision,
    MappingAction,
    VoiceAssistantRequest,
    VoiceAssistantResponse,
    VoiceStatus,
)


def test_ai_settings_are_read_from_rover_environment(monkeypatch):
    monkeypatch.setenv("ROVER_AI_ENABLED", "true")
    monkeypatch.setenv("ROVER_AI_BASE_URL", "https://gmn.chuangzuoli.com/v1")
    monkeypatch.setenv("ROVER_AI_MODEL", "gpt-5.6")
    monkeypatch.setenv("ROVER_AI_API_KEY", "runtime-secret")

    settings = Settings(_env_file=None)

    assert settings.ai_enabled is True
    assert settings.ai_base_url == "https://gmn.chuangzuoli.com/v1"
    assert settings.ai_model == "gpt-5.6"
    assert isinstance(settings.ai_api_key, SecretStr)
    assert settings.ai_api_key.get_secret_value() == "runtime-secret"


def test_enabled_assistant_configuration_requires_key_and_valid_url():
    with pytest.raises(ValueError, match="ROVER_AI_API_KEY"):
        Settings(ai_enabled=True, ai_api_key=None).validate_assistant_configuration()

    with pytest.raises(ValueError, match="http or https"):
        Settings(
            ai_enabled=True,
            ai_api_key=SecretStr("secret"),
            ai_base_url="gmn.chuangzuoli.com/v1",
        ).validate_assistant_configuration()


def test_mapping_action_rejects_unknown_action():
    with pytest.raises(ValidationError):
        MappingAction(type="cmd_vel", map_name=None)


def test_mapping_action_requires_map_name_only_for_save():
    assert MappingAction(type="mapping_start").map_name is None
    assert MappingAction(type="mapping_save", map_name="floor_1").map_name == "floor_1"

    with pytest.raises(ValidationError):
        MappingAction(type="mapping_save", map_name=None)

    for invalid_name in ("", "../outside", "maps/floor", "maps\\floor", "bad\nname"):
        with pytest.raises(ValidationError):
            MappingAction(type="mapping_save", map_name=invalid_name)


def test_mapping_action_rejects_map_name_for_non_save_actions():
    with pytest.raises(ValidationError):
        MappingAction(type="mapping_start", map_name="floor_1")


def test_voice_request_rejects_non_local_source():
    with pytest.raises(ValidationError):
        VoiceAssistantRequest(
            schema_version=1,
            session_id="voice-1",
            turn_id="turn-1",
            transcript="状态",
            language="zh-CN",
            confidence=0.9,
            source="cloud-asr",
        )


def test_voice_request_enforces_schema_source_and_confidence_bounds():
    request = VoiceAssistantRequest(
        session_id="voice-1",
        turn_id="turn-1",
        transcript="状态",
        language="zh-CN",
        confidence=0.9,
    )
    assert request.schema_version == 1
    assert request.source == "local-sherpa-onnx"

    for kwargs in (
        {"schema_version": 2},
        {"confidence": 1.1},
        {"confidence": -0.1},
        {"transcript": ""},
    ):
        base = {
            "session_id": "voice-1",
            "turn_id": "turn-1",
            "transcript": "状态",
            "language": "zh-CN",
            "confidence": 0.9,
        }
        base.update(kwargs)
        with pytest.raises(ValidationError):
            VoiceAssistantRequest(**base)


def test_assistant_decision_and_response_are_bounded_contracts():
    decision = AssistantDecision(reply_text="当前为空闲。", action=None, confidence=0.98)
    assert decision.action is None

    response = VoiceAssistantResponse(
        session_id="voice-1",
        turn_id="turn-1",
        state="completed",
        reply_text="当前为空闲。",
    )
    assert response.schema_version == 1
    assert response.error is None

    with pytest.raises(ValidationError):
        AssistantDecision(reply_text="", confidence=0.5)


def test_voice_status_defaults_to_safe_empty_component_latencies():
    status = VoiceStatus(state="disabled", enabled=False)
    assert status.session_id is None
    assert status.turn_id is None
    assert status.component_latency_ms == {}
