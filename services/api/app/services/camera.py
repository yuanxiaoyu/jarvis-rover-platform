from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from collections.abc import AsyncIterator


class CameraService:
    """Small V4L2-to-MJPEG adapter with no in-memory frame queue."""

    def __init__(
        self,
        device: str = "/dev/video0",
        width: int = 1280,
        height: int = 720,
        fps: int = 60,
    ) -> None:
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps

    def status(self) -> dict[str, object]:
        if not os.path.exists(self.device):
            return {"available": False, "device": self.device, "error": "摄像头设备不存在"}
        if not os.access(self.device, os.R_OK):
            return {"available": False, "device": self.device, "error": "当前服务账户没有读取摄像头的权限"}
        if shutil.which("ffmpeg") is None:
            return {"available": False, "device": self.device, "error": "ffmpeg 不可用"}
        return {
            "available": True,
            "device": self.device,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "error": None,
        }

    async def frames(self) -> AsyncIterator[bytes]:
        status = self.status()
        if not status["available"]:
            raise RuntimeError(str(status["error"]))

        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "v4l2",
            "-input_format",
            "mjpeg",
            "-video_size",
            f"{self.width}x{self.height}",
            "-framerate",
            str(self.fps),
            "-thread_queue_size",
            "1",
            "-i",
            self.device,
            "-c:v",
            "copy",
            "-f",
            "mjpeg",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert process.stdout is not None
        buffer = bytearray()
        try:
            while True:
                chunk = await process.stdout.read(64 * 1024)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    if start < 0:
                        if len(buffer) > 2:
                            del buffer[:-2]
                        break
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if end < 0:
                        if start > 0:
                            del buffer[:start]
                        break
                    frame = bytes(buffer[start : end + 2])
                    del buffer[: end + 2]
                    yield frame
        finally:
            if process.returncode is None:
                process.terminate()
            with contextlib.suppress(ProcessLookupError):
                await process.wait()
