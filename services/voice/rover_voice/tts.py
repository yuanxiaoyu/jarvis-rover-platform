from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path


class PiperTtsPlayer:
    def __init__(self, model: str, config: str, playback_device: str, sample_rate: int = 22050):
        self.model, self.config, self.playback_device = model, config, playback_device
        self.sample_rate = sample_rate
        self.process: subprocess.Popen[bytes] | None = None
        self.playback: subprocess.Popen[bytes] | None = None

    def speak(self, text: str, stop_event) -> None:
        if not text or not text.strip():
            return
        if not Path(self.model).is_file() or not Path(self.config).is_file():
            raise FileNotFoundError("Piper model/config missing")
        if not self.playback_device:
            raise RuntimeError("playback device is not configured")
        if shutil.which("piper") is None or shutil.which("aplay") is None:
            raise RuntimeError("piper and aplay are required")
        self.process = subprocess.Popen(
            ["piper", "--model", self.model, "--config", self.config, "--output_raw"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.playback = subprocess.Popen(
            ["aplay", "-q", "-D", self.playback_device, "-f", "S16_LE", "-r", str(self.sample_rate),
             "-c", "1", "-t", "raw", "-"], stdin=self.process.stdout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            assert self.process.stdin is not None
            self.process.stdin.write(text.encode("utf-8"))
            self.process.stdin.close()
            while self.process.poll() is None:
                if stop_event.is_set():
                    self._terminate_group(self.process)
                    self._terminate_group(self.playback)
                    return
                self.process.wait(timeout=0.1)
            if self.process.returncode != 0:
                raise RuntimeError("Piper synthesis failed")
            if self.playback.wait(timeout=5) != 0 and not stop_event.is_set():
                raise RuntimeError("audio playback failed")
        except subprocess.TimeoutExpired as exc:
            self._terminate_group(self.process)
            self._terminate_group(self.playback)
            raise RuntimeError("Piper synthesis timeout") from exc
        finally:
            self._close_processes()

    @staticmethod
    def _terminate_group(process) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def _close_processes(self) -> None:
        for process in (self.process, self.playback):
            if process is not None and process.poll() is None:
                self._terminate_group(process)
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
        self.process = None
        self.playback = None
