from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class AudioPrerequisiteError(RuntimeError):
    pass


class AlsaAudioInput:
    def __init__(self, device: str, sample_rate: int = 16000, channels: int = 1):
        self.device, self.sample_rate, self.channels = device, sample_rate, channels
        self._closed = False

    async def start(self) -> AsyncIterator[bytes]:
        if not self.device:
            raise AudioPrerequisiteError("capture device is not configured")
        try:
            import sounddevice  # type: ignore
        except ImportError as exc:
            raise AudioPrerequisiteError("sounddevice is unavailable") from exc
        stream = sounddevice.RawInputStream(samplerate=self.sample_rate, channels=self.channels, dtype="int16", device=self.device, blocksize=320)
        with stream:
            while not self._closed:
                data, _ = stream.read(320)
                yield bytes(data)
                await asyncio.sleep(0)

    async def close(self) -> None:
        self._closed = True


class AlsaAudioOutput:
    def __init__(self, device: str, sample_rate: int = 16000):
        self.device, self.sample_rate = device, sample_rate

    def play_pcm(self, stream: AsyncIterator[bytes], stop_event) -> None:
        if not self.device:
            raise AudioPrerequisiteError("playback device is not configured")
        try:
            import sounddevice  # type: ignore
        except ImportError as exc:
            raise AudioPrerequisiteError("sounddevice is unavailable") from exc
        import asyncio as _asyncio
        output = sounddevice.RawOutputStream(samplerate=self.sample_rate, channels=1, dtype="int16", device=self.device)
        with output:
            async def consume():
                async for chunk in stream:
                    if stop_event.is_set():
                        break
                    output.write(chunk)
            _asyncio.run(consume())

    async def close(self) -> None:
        return None


def probe_capture_device(device: str) -> tuple[bool, str]:
    return (True, "ok") if device else (False, "capture device unavailable")


def probe_playback_device(device: str) -> tuple[bool, str]:
    return (True, "ok") if device else (False, "playback device unavailable")
