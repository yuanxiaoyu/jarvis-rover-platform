from __future__ import annotations
import subprocess
from pathlib import Path


class PiperTtsPlayer:
    def __init__(self, model: str, config: str, playback_device: str):
        self.model, self.config, self.playback_device = model, config, playback_device
        self.process = None

    def speak(self, text: str, stop_event) -> None:
        if not Path(self.model).is_file() or not Path(self.config).is_file():
            raise FileNotFoundError("Piper model/config missing")
        if stop_event.is_set():
            return
        self.process = subprocess.Popen(["piper", "--model", self.model, "--config", self.config], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            self.process.communicate(text.encode("utf-8"), timeout=30)
        finally:
            if stop_event.is_set() and self.process.poll() is None:
                self.process.kill()
