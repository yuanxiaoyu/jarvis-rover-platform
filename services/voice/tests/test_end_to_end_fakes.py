from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from rover_voice.contracts import AsrResult, VoiceState
from rover_voice.service import VoiceService


class FakeInput:
    async def start(self):
        if False:
            yield b""

    async def close(self):
        pass


class FakeWake:
    def __init__(self): self.hit = True
    def process(self, frame):
        hit, self.hit = self.hit, False
        return hit


class FakeAsr:
    def is_speech(self, frame): return False
    def transcribe(self, frames): return AsrResult("当前状态", 1.0, len(frames) * 20)


class FakeTts:
    def __init__(self): self.spoken = []
    def speak(self, text, stop_event): self.spoken.append(text)


class FakeGateway:
    def __init__(self): self.requests = []; self.heartbeats = []
    async def assistant(self, request):
        self.requests.append(request)
        return SimpleNamespace(reply_text="当前建图空闲。")
    async def heartbeat(self, status): self.heartbeats.append(status)
    async def close(self): pass


def config():
    return SimpleNamespace(record_max_seconds=15, sample_rate=16000, vad_silence_ms=0,
                           followup_seconds=8, min_confidence=0.35)


@pytest.mark.anyio
async def test_fake_audio_runs_local_asr_gateway_and_tts():
    tts, gateway = FakeTts(), FakeGateway()
    service = VoiceService(config(), FakeInput(), FakeWake(), FakeAsr(), tts, gateway)
    service.enable()
    service.process_frame(b"wake")
    service.process_frame(b"speech")
    await service.run_pending_once()
    await service.run_pending_once()
    assert gateway.requests[0].transcript == "当前状态"
    assert tts.spoken == ["当前建图空闲。"]
    assert service.runtime.state is VoiceState.CAPTURING
