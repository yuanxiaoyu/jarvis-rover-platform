from pathlib import Path

import pytest

from rover_voice.config import VoiceConfig


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_voice_config_defaults_to_disabled_and_local_tts_fields():
    # Ignore the developer's local .env so this test exercises class defaults.
    config = VoiceConfig(_env_file=None)
    assert config.enabled is False
    assert config.wakeword_phrase == "贾维斯"
    assert config.tts_engine == "pocket_tts"
    assert config.tts_device == "cpu"
    assert config.tts_playback_sample_rate == 24000
    assert config.gateway_token is None


def test_voice_config_normalizes_wakeword_phrase():
    assert VoiceConfig(_env_file=None, wakeword_phrase="  贾维斯  ").wakeword_phrase == "贾维斯"
    with pytest.raises(ValueError, match="wakeword phrase"):
        VoiceConfig(_env_file=None, wakeword_phrase="   ")


def test_enabled_config_requires_pocket_tts_assets(tmp_path):
    config = VoiceConfig(
        enabled=True,
        capture_device="hw:Capture",
        playback_device="hw:Playback",
        wakeword_model=str(tmp_path / "wake.onnx"),
        asr_model_dir=str(tmp_path / "asr"),
        tts_model_dir=str(tmp_path / "tts"),
        tts_checkpoint=str(tmp_path / "tts" / "model.safetensors"),
        tts_voice_state=str(tmp_path / "tts" / "voice.safetensors"),
        gateway_token="voice-only-token",
    )
    try:
        config.validate_prerequisites()
    except ValueError as exc:
        assert "wakeword" in str(exc) or "ASR" in str(exc) or "Pocket TTS" in str(exc)
    else:
        raise AssertionError("missing voice assets must fail closed")


def test_enabled_config_accepts_sherpa_keyword_spotter_directory(tmp_path, monkeypatch):
    model_dir = tmp_path / "kws"
    (model_dir / "test_wavs").mkdir(parents=True)
    for name in ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx", "test_wavs/keywords.txt"):
        path = model_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")
    asr_dir = tmp_path / "asr"
    asr_dir.mkdir()
    for name in ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx"):
        (asr_dir / name).write_bytes(b"model")
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    checkpoint = tts_dir / "model.safetensors"
    voice = tts_dir / "voice.safetensors"
    checkpoint.write_bytes(b"model")
    voice.write_bytes(b"voice")
    (tts_dir / "config.yaml").write_text("weights_path: model.safetensors\n", encoding="utf-8")
    monkeypatch.setattr("rover_voice.audio.probe_capture_device", lambda device: (True, "ok"))
    monkeypatch.setattr("rover_voice.audio.probe_playback_device", lambda device: (True, "ok"))
    config = VoiceConfig(
        _env_file=None,
        enabled=True,
        capture_device="plughw:CARD=Device,DEV=0",
        playback_device="plughw:CARD=Device,DEV=0",
        wakeword_model=str(model_dir),
        asr_model_dir=str(asr_dir),
        tts_model_dir=str(tts_dir),
        tts_checkpoint=str(checkpoint),
        tts_voice_state=str(voice),
        gateway_token="token",
    )
    config.validate_prerequisites()


def test_enabled_config_accepts_sherpa_vits_without_pocket_checkpoint(tmp_path, monkeypatch):
    model_dir = tmp_path / "kws"
    (model_dir / "test_wavs").mkdir(parents=True)
    for name in ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx", "test_wavs/keywords.txt"):
        path = model_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")
    asr_dir = tmp_path / "asr"
    asr_dir.mkdir()
    for name in ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx"):
        (asr_dir / name).write_bytes(b"model")
    tts_dir = tmp_path / "vits"
    tts_dir.mkdir()
    for name in ("model.onnx", "lexicon.txt", "tokens.txt"):
        (tts_dir / name).write_bytes(b"model")
    monkeypatch.setattr("rover_voice.audio.probe_capture_device", lambda device: (True, "ok"))
    monkeypatch.setattr("rover_voice.audio.probe_playback_device", lambda device: (True, "ok"))
    config = VoiceConfig(
        _env_file=None,
        enabled=True,
        capture_device="plughw:CARD=Device,DEV=0",
        playback_device="plughw:CARD=Device,DEV=0",
        wakeword_model=str(model_dir),
        asr_model_dir=str(asr_dir),
        tts_model_dir=str(tts_dir),
        tts_engine="sherpa_vits",
        gateway_token="token",
    )
    config.validate_prerequisites()


def test_voice_systemd_unit_is_rendered_for_the_checked_out_repository():
    unit = (REPOSITORY_ROOT / "deploy" / "jarvis-rover-voice.service").read_text(encoding="utf-8")
    assert "@REPO_DIR@/services/voice" in unit
    assert "@VOICE_PYTHON@ -m rover_voice.cli run" in unit
    assert "@SERVICE_USER@" in unit
    assert "ProtectHome=read-only" in unit
    assert "SupplementaryGroups=audio" in unit
    assert "Requires=" not in unit
    assert "/opt/jarvis-rover/voice" not in unit
