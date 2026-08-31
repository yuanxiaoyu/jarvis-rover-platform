from rover_voice.config import VoiceConfig
from rover_voice.contracts import VoiceState
from rover_voice.state_machine import StateMachine


def test_imports_are_hardware_free():
    assert StateMachine().runtime.state is VoiceState.DISABLED


def test_config_rejects_non_standard_audio():
    config = VoiceConfig(sample_rate=8000)
    try:
        config.validate_prerequisites()
    except ValueError as exc:
        assert "16 kHz" in str(exc)
    else:
        raise AssertionError("invalid sample rate accepted")
