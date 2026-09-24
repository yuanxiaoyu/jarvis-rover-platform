from __future__ import annotations

import threading
from pathlib import Path

import pytest

from rover_voice.config import VoiceConfig
from rover_voice.tts import PocketTtsError, PocketTtsPlayer, SherpaVitsTtsPlayer
from rover_voice.wakeword import (
    OpenWakeWordDetector,
    SherpaKeywordSpotterDetector,
    _keyword_pronunciation,
    _wake_text_matches,
)
from rover_voice.asr import SherpaOnnxRecognizer


class FakeAudio:
    sample_rate = 12000
    def __init__(self, count: int = 4):
        self.samples = [0.25] * count


class FakeVitsAudio:
    sample_rate = 8000

    def __init__(self, count: int = 8):
        self.samples = [0.1] * count


class FakeModel:
    sample_rate = 12000
    def __init__(self, count: int = 4):
        self.voice_args = None
        self.text = None
        self.count = count

    def get_state_for_audio_prompt(self, path: str):
        self.voice_args = path
        return "voice-state"

    def generate_audio(self, voice, text: str):
        assert voice == "voice-state"
        self.text = text
        return FakeAudio(self.count)


class FakeStdin:
    def __init__(self, on_write=None):
        self.data = bytearray()
        self.closed = False
        self.on_write = on_write

    def write(self, data: bytes):
        self.data.extend(data)
        if self.on_write:
            self.on_write()

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeProcess:
    pid = 99_999_999

    def __init__(self, on_write=None):
        self.returncode = None
        self.stdin = FakeStdin(on_write)
        self.terminated = False
        self.killed = False
        self.wait_timeout = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_timeout = timeout
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


def files(tmp_path: Path):
    model_dir = tmp_path / "pocket-tts"
    model_dir.mkdir()
    checkpoint = model_dir / "model.safetensors"
    voice = model_dir / "voice.safetensors"
    checkpoint.write_bytes(b"checkpoint")
    voice.write_bytes(b"voice")
    return model_dir, checkpoint, voice


def test_pocket_tts_loads_fixed_local_checkpoint_and_voice_state(tmp_path):
    model_dir, checkpoint, voice = files(tmp_path)
    model = FakeModel()
    calls = []

    def loader(**kwargs):
        calls.append(kwargs)
        return model

    processes = []
    player = PocketTtsPlayer(
        str(model_dir), str(checkpoint), str(voice), "plughw:CARD=Speaker",
        model_loader=loader,
        playback_factory=lambda *args, **kwargs: processes.append(FakeProcess()) or processes[-1],
        command_exists=lambda command: "/usr/bin/aplay",
    )
    player.speak("  你好  ", threading.Event())
    assert calls == [{"checkpoint": str(checkpoint), "device": "cpu"}]
    assert model.voice_args == str(voice)
    assert model.text == "你好"
    assert processes[0].stdin.closed
    assert len(processes[0].stdin.data) > 0


def test_pocket_tts_streams_first_chunk_before_generation_finishes(tmp_path):
    model_dir, checkpoint, voice = files(tmp_path)
    processes = []

    class StreamingModel(FakeModel):
        def generate_audio_stream(self, model_state, text_to_generate):
            assert model_state == "voice-state"
            assert text_to_generate == "流式测试"
            assert processes, "playback must start before the first generated chunk"
            yield FakeAudio(count=256)
            yield FakeAudio(count=256)

    player = PocketTtsPlayer(
        str(model_dir), str(checkpoint), str(voice), "speaker",
        model_loader=lambda **kwargs: StreamingModel(),
        playback_factory=lambda *args, **kwargs: processes.append(FakeProcess()) or processes[-1],
        command_exists=lambda command: "/usr/bin/aplay",
    )
    player.speak("流式测试", threading.Event())

    assert processes[0].stdin.closed
    assert len(processes[0].stdin.data) > 0


def test_pocket_tts_rejects_missing_prerequisites(tmp_path):
    model_dir = tmp_path / "missing"
    player = PocketTtsPlayer(str(model_dir), str(model_dir / "model"), str(model_dir / "voice"), "speaker")
    with pytest.raises(FileNotFoundError):
        player.speak("你好", threading.Event())


def test_pocket_tts_interruption_terminates_playback(tmp_path):
    model_dir, checkpoint, voice = files(tmp_path)
    stop_event = threading.Event()
    process = FakeProcess(on_write=stop_event.set)
    player = PocketTtsPlayer(
        str(model_dir), str(checkpoint), str(voice), "speaker",
        model_loader=lambda **kwargs: FakeModel(count=4096),
        playback_factory=lambda *args, **kwargs: process,
        command_exists=lambda command: "/usr/bin/aplay",
    )
    player.speak("中断测试", stop_event)
    assert process.terminated


def test_pocket_tts_does_not_start_without_aplay(tmp_path):
    model_dir, checkpoint, voice = files(tmp_path)
    player = PocketTtsPlayer(
        str(model_dir), str(checkpoint), str(voice), "speaker",
        model_loader=lambda **kwargs: FakeModel(), command_exists=lambda command: None,
    )
    with pytest.raises(PocketTtsError, match="aplay"):
        player.speak("你好", threading.Event())


def test_sherpa_vits_uses_local_model_and_usb_playback(tmp_path, monkeypatch):
    model_dir = tmp_path / "vits"
    model_dir.mkdir()
    for name in ("model.onnx", "lexicon.txt", "tokens.txt"):
        (model_dir / name).write_bytes(b"model")

    class GenerationConfig:
        sid = None
        speed = None

    class FakeSherpa:
        pass

    FakeSherpa.GenerationConfig = GenerationConfig

    class FakeVits:
        sample_rate = 8000

        def __init__(self):
            self.text = None
            self.generation = None

        def generate(self, text, generation):
            self.text = text
            self.generation = generation
            return FakeVitsAudio()

    vits = FakeVits()
    monkeypatch.setitem(__import__("sys").modules, "sherpa_onnx", FakeSherpa)
    process = FakeProcess()
    player = SherpaVitsTtsPlayer(
        str(model_dir), "plughw:CARD=Device,DEV=0", speaker_id=7,
        tts_factory=lambda **kwargs: vits,
        playback_factory=lambda *args, **kwargs: process,
        command_exists=lambda command: "/usr/bin/aplay",
    )
    player.speak("  你好，贾维斯  ", threading.Event())
    assert vits.text == "你好，贾维斯"
    assert vits.generation.sid == 7
    assert process.stdin.closed
    assert len(process.stdin.data) > 0


def test_sherpa_vits_callback_stream_is_not_played_twice(tmp_path, monkeypatch):
    model_dir = tmp_path / "vits"
    model_dir.mkdir()
    for name in ("model.onnx", "lexicon.txt", "tokens.txt"):
        (model_dir / name).write_bytes(b"model")

    class GenerationConfigFake:
        sid = None
        speed = None

    class FakeSherpa:
        GenerationConfig = GenerationConfigFake

    class CallbackVits:
        sample_rate = 8000

        def generate(self, text, generation, callback=None):
            assert callback is not None
            callback(FakeVitsAudio(count=80), 0.5)
            # The complete return value must not be written a second time when
            # the callback already delivered the stream.
            return FakeVitsAudio(count=8000)

    monkeypatch.setitem(__import__("sys").modules, "sherpa_onnx", FakeSherpa)
    process = FakeProcess()
    player = SherpaVitsTtsPlayer(
        str(model_dir), "speaker", tts_factory=lambda **kwargs: CallbackVits(),
        playback_factory=lambda *args, **kwargs: process,
        command_exists=lambda command: "/usr/bin/aplay",
    )
    player.speak("流式测试", threading.Event())

    assert process.stdin.closed
    assert len(process.stdin.data) < 1000


def test_tts_playback_timeout_scales_with_audio_duration(tmp_path, monkeypatch):
    model_dir = tmp_path / "vits"
    model_dir.mkdir()
    for name in ("model.onnx", "lexicon.txt", "tokens.txt"):
        (model_dir / name).write_bytes(b"model")

    class GenerationConfig:
        sid = 0
        speed = 0

    class FakeSherpa:
        pass

    FakeSherpa.GenerationConfig = GenerationConfig

    class LongAudio:
        sample_rate = 8000
        samples = [0.1] * 48000  # six seconds of PCM at the model rate

    class LongVits:
        def generate(self, text, generation):
            return LongAudio()

    monkeypatch.setitem(__import__("sys").modules, "sherpa_onnx", FakeSherpa)
    process = FakeProcess()
    player = SherpaVitsTtsPlayer(
        str(model_dir), "speaker", tts_factory=lambda **kwargs: LongVits(),
        playback_factory=lambda *args, **kwargs: process,
        command_exists=lambda command: "/usr/bin/aplay",
    )
    player.speak("较长测试", threading.Event())
    assert process.wait_timeout > 5


def test_sherpa_vits_rejects_incomplete_model(tmp_path):
    model_dir = tmp_path / "vits"
    model_dir.mkdir()
    player = SherpaVitsTtsPlayer(str(model_dir), "speaker")
    with pytest.raises(FileNotFoundError, match="model.onnx"):
        player.speak("你好", threading.Event())


def test_wakeword_detector_accepts_injected_model_without_importing_runtime(tmp_path):
    class Model:
        def predict(self, frame):
            return {"贾维斯": 0.9}

    path = tmp_path / "wake.onnx"
    path.write_bytes(b"model")
    detector = OpenWakeWordDetector(str(path), wakeword_phrase="贾维斯", threshold=0.8, model=Model())
    assert detector.process(b"\x00\x00" * 160)
    assert not detector.process(b"\x00\x00" * 160)


def test_wakeword_detector_ignores_other_model_predictions(tmp_path):
    class Model:
        def predict(self, frame):
            return {"你好贾维斯": 0.99, "贾维斯": 0.1}

    path = tmp_path / "wake.onnx"
    path.write_bytes(b"model")
    detector = OpenWakeWordDetector(str(path), wakeword_phrase="贾维斯", threshold=0.8, model=Model())
    assert not detector.process(b"\x00\x00" * 160)


def test_wakeword_detector_accepts_model_file_label_alias(tmp_path):
    class Model:
        def predict(self, frame):
            return {"javis": 0.9}

    path = tmp_path / "javis.onnx"
    path.write_bytes(b"model")
    detector = OpenWakeWordDetector(str(path), wakeword_phrase="贾维斯", threshold=0.8, model=Model())
    assert detector.process(b"\x00\x00" * 160)


def test_sherpa_keyword_spotter_accepts_only_configured_phrase():
    class Stream:
        def accept_waveform(self, sample_rate, samples):
            assert sample_rate == 16000
            assert samples

    class Spotter:
        def __init__(self):
            self.reset_count = 0

        def is_ready(self, stream):
            return self.reset_count == 0

        def decode_stream(self, stream):
            pass

        def get_result(self, stream):
            return "贾维斯"

        def reset_stream(self, stream):
            self.reset_count += 1

    detector = SherpaKeywordSpotterDetector(
        "/unused", spotter=Spotter(), stream=Stream(), threshold=0.25,
    )
    assert detector.process(b"\x00\x00" * 160)


def test_sherpa_keyword_spotter_rejects_unprovisioned_phrase():
    with pytest.raises(ValueError, match="pronunciation"):
        _keyword_pronunciation("小车")


def test_wake_text_matches_common_jarvis_asr_variants():
    assert _wake_text_matches("贾维斯", "嗯，甲为斯")
    assert _wake_text_matches("贾维斯", "亚威斯")
    assert _wake_text_matches("贾维斯", "jarvis")
    assert not _wake_text_matches("贾维斯", "讲一个冷笑话")


def test_wake_asr_fallback_uses_window_energy_when_tail_frame_is_silent():
    class Stream:
        def accept_waveform(self, sample_rate, samples):
            pass

    class Spotter:
        def is_ready(self, stream):
            return False

    class FallbackAsr:
        def __init__(self):
            self.calls = 0

        def transcribe(self, frames):
            self.calls += 1
            return type("Result", (), {"text": "亚威斯"})()

    now = [0.0]
    asr = FallbackAsr()
    detector = SherpaKeywordSpotterDetector(
        "/unused", spotter=Spotter(), stream=Stream(), fallback_asr=asr,
        clock=lambda: now[0], fallback_energy_threshold=100,
    )
    speech = (1200).to_bytes(2, "little", signed=True) * 320
    silence = b"\x00\x00" * 320
    for _ in range(20):
        detector.process(speech)
        now[0] += 0.1
    now[0] += 2.0
    assert detector.process(silence)
    assert asr.calls == 1


def test_asr_missing_model_is_reported_without_importing_sherpa(tmp_path):
    recognizer = SherpaOnnxRecognizer(str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError):
        recognizer.transcribe([b"\x00\x00"])


def test_voice_config_uses_pocket_tts_names_only():
    config = VoiceConfig()
    assert config.tts_checkpoint == ""
    assert config.tts_voice_state == ""
    assert not hasattr(config, "tts_model")
