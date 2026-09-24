from __future__ import annotations

import asyncio
from types import SimpleNamespace

from rover_voice.contracts import AsrResult, VoiceState
from rover_voice.service import VoiceService


class FakeInput:
    async def start(self):
        if False:
            yield b""

    async def close(self):
        pass


class FakeWake:
    def __init__(self):
        self.hit = True

    def process(self, frame):
        hit, self.hit = self.hit, False
        return hit


class FakeAsr:
    def is_speech(self, frame):
        return False

    def transcribe(self, frames):
        return AsrResult("当前状态", 1.0, len(frames) * 20)


class FakeTts:
    def __init__(self):
        self.spoken = []

    def speak(self, text, stop_event):
        self.spoken.append(text)


class FakeGateway:
    def __init__(self):
        self.requests = []
        self.heartbeats = []

    async def assistant(self, request):
        self.requests.append(request)
        return SimpleNamespace(reply_text="当前建图空闲。", state="completed")

    async def heartbeat(self, status):
        self.heartbeats.append(status)

    async def close(self):
        pass


def config():
    return SimpleNamespace(
        record_max_seconds=15,
        sample_rate=16000,
        vad_silence_ms=0,
        followup_seconds=8,
        wake_ack_text="我在，请说。",
        min_confidence=0.35,
        max_audio_queue_frames=750,
        heartbeat_interval_seconds=3,
    )


def test_fake_audio_runs_local_asr_gateway_and_tts():
    async def run():
        tts, gateway = FakeTts(), FakeGateway()
        service = VoiceService(config(), FakeInput(), FakeWake(), FakeAsr(), tts, gateway)
        service.enable()
        service.process_frame(b"wake")
        await service.run_pending_once()
        service.process_frame(b"speech")
        await service.run_pending_once()
        await service.run_pending_once()
        assert gateway.requests[0].transcript == "当前状态"
        assert tts.spoken == ["我在，请说。", "当前建图空闲。"]
        assert service.runtime.state is VoiceState.CAPTURING
        assert len(gateway.heartbeats) >= 1

    asyncio.run(run())


def test_empty_asr_uses_local_prompt_and_bounded_followup():
    class EmptyAsr(FakeAsr):
        def transcribe(self, frames):
            return AsrResult("", 0.0, 0)

    async def run():
        tts, gateway = FakeTts(), FakeGateway()
        service = VoiceService(config(), FakeInput(), FakeWake(), EmptyAsr(), tts, gateway)
        service.enable()
        service.process_frame(b"wake")
        await service.run_pending_once()
        service.process_frame(b"speech")
        await service.run_pending_once()
        assert service.runtime.state is VoiceState.CAPTURING
        assert tts.spoken == ["我在，请说。", "没有听清，请再说一次。"]
        assert gateway.requests == []

    asyncio.run(run())


def test_assistant_failure_does_not_escape_local_service():
    class FailedGateway(FakeGateway):
        async def assistant(self, request):
            raise RuntimeError("secret provider detail")

    async def run():
        tts, gateway = FakeTts(), FailedGateway()
        service = VoiceService(config(), FakeInput(), FakeWake(), FakeAsr(), tts, gateway)
        service.enable()
        service.process_frame(b"wake")
        await service.run_pending_once()
        service.process_frame(b"speech")
        await service.run_pending_once()
        await service.run_pending_once()
        assert service.runtime.state is VoiceState.WAKE_LISTENING
        assert tts.spoken == ["我在，请说。", "助手服务暂时不可用。"]
        assert service.runtime.last_error is None

    asyncio.run(run())


def test_tts_failure_recovers_to_wake_listening():
    class FailedTts(FakeTts):
        def speak(self, text, stop_event):
            raise RuntimeError("speaker timeout")

    async def run():
        tts, gateway = FailedTts(), FakeGateway()
        service = VoiceService(config(), FakeInput(), FakeWake(), FakeAsr(), tts, gateway)
        service.enable()
        service.process_frame(b"wake")
        await service.run_pending_once()
        service.process_frame(b"speech")
        await service.run_pending_once()
        await service.run_pending_once()
        assert service.runtime.state is VoiceState.WAKE_LISTENING
        assert any(status.state is VoiceState.TTS_ERROR for status in gateway.heartbeats)
        assert gateway.heartbeats[-1].state is VoiceState.WAKE_LISTENING


def test_wake_ack_is_interruptible_by_immediate_speech():
    class SpeakingAsr(FakeAsr):
        def is_speech(self, frame):
            return frame == b"speech"

    async def run():
        tts, gateway = FakeTts(), FakeGateway()
        service = VoiceService(config(), FakeInput(), FakeWake(), SpeakingAsr(), tts, gateway)
        service.enable()
        service.process_frame(b"wake")
        assert service.runtime.state is VoiceState.SPEAKING
        service.process_frame(b"speech")
        await service.run_pending_once()
        assert service.runtime.state is VoiceState.CAPTURING
        assert tts.spoken == []

    asyncio.run(run())

    asyncio.run(run())


def test_speech_interrupts_tts_and_starts_a_new_capture():
    class SpeakingAsr(FakeAsr):
        def is_speech(self, frame):
            return frame == b"speech"

    service = VoiceService(config(), FakeInput(), FakeWake(), SpeakingAsr(), FakeTts(), FakeGateway())
    service.enable()
    service.transition(VoiceState.SPEAKING)
    service.process_frame(b"speech")

    assert service.runtime.state is VoiceState.CAPTURING
    assert service.stop_event.is_set()
    assert list(service.frames) == [b"speech"]
