from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_voice_unit_is_optional_and_audio_scoped():
    unit = (ROOT / "deploy/jarvis-rover-voice.service").read_text()
    assert "After=network-online.target jarvis-rover-runtime.service" in unit
    assert "Requires=jarvis-rover-runtime.service" not in unit
    assert "DeviceAllow=/dev/snd/*" in unit
    assert "mapping start" not in unit.lower()
    assert "cmd_vel" not in unit


def test_prerequisite_scripts_are_non_destructive():
    checker = (ROOT / "scripts/check_voice_prerequisites.sh").read_text()
    audio = (ROOT / "scripts/test_voice_audio.sh").read_text()
    assert "docker compose down" not in checker
    assert "mapping/start" not in checker
    assert "--play-test-tone" in audio
    assert "ROVER_VOICE_CAPTURE_DEVICE" in audio
    assert "ROVER_VOICE_PLAYBACK_DEVICE" in audio
