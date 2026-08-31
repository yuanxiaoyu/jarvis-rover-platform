from __future__ import annotations
import time


class OpenWakeWordDetector:
    def __init__(self, model_path: str, threshold: float = 0.5, cooldown_seconds: float = 2.0):
        self.model_path, self.threshold, self.cooldown_seconds = model_path, threshold, cooldown_seconds
        self._last = 0.0
        self._model = None

    def _load(self):
        if self._model is None:
            from pathlib import Path
            if not Path(self.model_path).is_file():
                raise FileNotFoundError(self.model_path)
            try:
                from openwakeword.model import Model
                self._model = Model(wakeword_models=[self.model_path])
            except ImportError as exc:
                raise RuntimeError("openWakeWord is unavailable") from exc

    def process(self, frame: bytes) -> bool:
        self._load()
        if time.monotonic() - self._last < self.cooldown_seconds:
            return False
        score = max(self._model.predict(frame).values())
        if score >= self.threshold:
            self._last = time.monotonic()
            return True
        return False
