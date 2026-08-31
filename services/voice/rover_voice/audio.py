from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import shutil
import subprocess


class AudioPrerequisiteError(RuntimeError):
    pass


class AlsaAudioInput:
    def __init__(self, device: str, sample_rate: int = 16000, channels: int = 1, frame_samples: int = 320):
        self.device, self.sample_rate, self.channels = device, sample_rate, channels
        self.frame_samples = frame_samples
        self._closed = False
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> AsyncIterator[bytes]:
        self._validate()
        if shutil.which("arecord") is None:
            raise AudioPrerequisiteError("arecord is unavailable")
        self._process = await asyncio.create_subprocess_exec(
            "arecord", "-q", "-D", self.device, "-f", "S16_LE", "-r", str(self.sample_rate),
            "-c", str(self.channels), "-t", "raw", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        assert self._process.stdout is not None
        frame_bytes = self.frame_samples * self.channels * 2
        try:
            while not self._closed:
                data = await self._process.stdout.readexactly(frame_bytes)
                yield data
        except asyncio.IncompleteReadError:
            if not self._closed:
                error = b""
                if self._process.stderr is not None:
                    error = await self._process.stderr.read()
                raise AudioPrerequisiteError(error.decode(errors="replace")[:160] or "capture stream ended")
        finally:
            await self.close()

    def _validate(self) -> None:
        if not self.device:
            raise AudioPrerequisiteError("capture device is not configured")
        if self.sample_rate != 16000 or self.channels != 1:
            raise AudioPrerequisiteError("capture must be 16 kHz mono PCM16")

    async def close(self) -> None:
        self._closed = True
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=1)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()


class AlsaAudioOutput:
    def __init__(self, device: str, sample_rate: int = 16000):
        self.device, self.sample_rate = device, sample_rate

    def play_pcm(self, stream: AsyncIterator[bytes], stop_event) -> None:
        if not self.device:
            raise AudioPrerequisiteError("playback device is not configured")
        if shutil.which("aplay") is None:
            raise AudioPrerequisiteError("aplay is unavailable")
        process = subprocess.Popen(
            ["aplay", "-q", "-D", self.device, "-f", "S16_LE", "-r", str(self.sample_rate),
             "-c", "1", "-t", "raw", "-"], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        try:
            async def consume() -> None:
                assert process.stdin is not None
                async for chunk in stream:
                    if stop_event.is_set():
                        break
                    process.stdin.write(chunk)
                    process.stdin.flush()
                if process.stdin:
                    process.stdin.close()

            asyncio.run(consume())
            if process.wait(timeout=2) != 0:
                raise AudioPrerequisiteError("playback device rejected PCM stream")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)

    async def close(self) -> None:
        return None


def _probe(device: str, command: str) -> tuple[bool, str]:
    if not device:
        return False, f"{command} device unavailable"
    if shutil.which(command) is None:
        return False, f"{command} is unavailable"
    try:
        result = subprocess.run([command, "-q", "-D", device, "--dump-hw-params", "-"],
                                input=b"", capture_output=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{command} probe failed: {type(exc).__name__}"
    if result.returncode != 0:
        return False, f"{command} cannot open configured device"
    return True, "ok"


def probe_capture_device(device: str) -> tuple[bool, str]:
    return _probe(device, "arecord")


def probe_playback_device(device: str) -> tuple[bool, str]:
    return _probe(device, "aplay")
