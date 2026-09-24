from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import AsyncIterator


class AudioPrerequisiteError(RuntimeError):
    pass


class AlsaAudioInput:
    """Read bounded-size raw PCM frames from an explicitly named ALSA device."""

    def __init__(self, device: str, sample_rate: int = 16000, channels: int = 1, frame_samples: int = 320):
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_samples = frame_samples
        self._closed = False
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> AsyncIterator[bytes]:
        self._validate()
        if shutil.which("arecord") is None:
            raise AudioPrerequisiteError("arecord is unavailable")
        self._closed = False
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
                if len(data) != frame_bytes:
                    raise AudioPrerequisiteError("capture returned an invalid PCM frame")
                yield data
        except asyncio.IncompleteReadError as exc:
            if not self._closed:
                detail = b""
                if self._process.stderr is not None:
                    detail = await self._process.stderr.read(512)
                reason = detail.decode(errors="replace").strip()[:160]
                raise AudioPrerequisiteError(reason or "capture stream ended") from exc
        finally:
            await self.close()

    def _validate(self) -> None:
        if not self.device:
            raise AudioPrerequisiteError("capture device is not configured")
        if self.sample_rate != 16000 or self.channels != 1:
            raise AudioPrerequisiteError("capture must be 16 kHz mono PCM16")
        if self.frame_samples <= 0:
            raise AudioPrerequisiteError("frame size must be positive")

    async def close(self) -> None:
        self._closed = True
        process = self._process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._process = None


def _probe(device: str, command: str) -> tuple[bool, str]:
    if not device:
        return False, f"{command} device unavailable"
    if shutil.which(command) is None:
        return False, f"{command} is unavailable"
    if command == "arecord":
        args = [
            command, "-q", "-D", device, "-f", "S16_LE", "-r", "16000",
            "-c", "1", "-d", "1", "-t", "raw", "/dev/null",
        ]
    else:
        args = [
            command, "-q", "-D", device, "-f", "S16_LE", "-r", "8000",
            "-c", "1", "-d", "1", "-t", "raw", "/dev/zero",
        ]
    try:
        result = subprocess.run(
            args, capture_output=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{command} probe failed: {type(exc).__name__}"
    if result.returncode != 0:
        return False, f"{command} cannot open configured device"
    return True, "ok"


def probe_capture_device(device: str) -> tuple[bool, str]:
    return _probe(device, "arecord")


def probe_playback_device(device: str) -> tuple[bool, str]:
    return _probe(device, "aplay")
