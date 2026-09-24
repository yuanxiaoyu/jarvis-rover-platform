from pathlib import Path

from rover_voice.tts import PocketTtsPlayer


VOICE_ROOT = Path(__file__).resolve().parents[1]


def test_voice_sources_do_not_contain_piper_or_cloud_tts_fallbacks():
    source = "\n".join(path.read_text() for path in (VOICE_ROOT / "rover_voice").rglob("*.py"))
    assert "Piper" not in source
    assert "requests.post" not in source
    assert "openai" not in source.casefold()


def test_tts_constructor_does_not_accept_provider_credentials():
    parameters = PocketTtsPlayer.__init__.__code__.co_varnames
    assert "api_key" not in parameters
    assert "gateway_token" not in parameters
