from __future__ import annotations
from .contracts import AsrResult


class SherpaOnnxRecognizer:
    def __init__(self, model_dir: str, min_confidence: float = 0.35):
        self.model_dir, self.min_confidence = model_dir, min_confidence
        self._recognizer = None

    def _load(self):
        if self._recognizer is None:
            from pathlib import Path
            if not Path(self.model_dir).is_dir():
                raise FileNotFoundError(self.model_dir)
            try:
                import sherpa_onnx
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(model=self.model_dir)
            except ImportError as exc:
                raise RuntimeError("sherpa-onnx is unavailable") from exc

    def is_speech(self, frame: bytes) -> bool:
        return any(frame)

    def transcribe(self, frames: list[bytes]) -> AsrResult:
        self._load()
        if not frames:
            return AsrResult("", None, 0)
        return AsrResult("", 0.0, len(frames) * 20)
