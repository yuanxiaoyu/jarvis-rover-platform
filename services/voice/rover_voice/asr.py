from __future__ import annotations

import array
from pathlib import Path

from .contracts import AsrResult


class SherpaOnnxRecognizer:
    """Lazy sherpa-onnx offline recognizer for locally buffered PCM16 frames."""

    def __init__(self, model_dir: str, min_confidence: float = 0.35, sample_rate: int = 16000):
        self.model_dir, self.min_confidence, self.sample_rate = model_dir, min_confidence, sample_rate
        self._recognizer = None

    def _load(self):
        if self._recognizer is not None:
            return self._recognizer
        directory = Path(self.model_dir)
        if not directory.is_dir():
            raise FileNotFoundError(self.model_dir)
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx is unavailable") from exc
        def one(pattern: str) -> str:
            matches = sorted(directory.glob(pattern))
            if not matches:
                raise FileNotFoundError(f"ASR model file matching {pattern} is missing")
            return str(matches[0])
        try:
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=one("*encoder*.onnx"), decoder=one("*decoder*.onnx"),
                joiner=one("*joiner*.onnx"), tokens=one("tokens.txt"),
                num_threads=1, sample_rate=self.sample_rate, feature_dim=80,
            )
        except (AttributeError, TypeError) as exc:
            raise RuntimeError("unsupported sherpa-onnx transducer model") from exc
        return self._recognizer

    def is_speech(self, frame: bytes) -> bool:
        if len(frame) < 2:
            return False
        samples = array.array("h")
        samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
        if not samples:
            return False
        # Energy VAD is deliberately conservative and keeps all ASR local. A
        # configured sherpa VAD can replace this adapter without changing the
        # service contract.
        return sum(abs(sample) for sample in samples) / len(samples) > 350

    def transcribe(self, frames: list[bytes]) -> AsrResult:
        if not frames:
            return AsrResult("", None, 0)
        recognizer = self._load()
        samples = array.array("h")
        for frame in frames:
            samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
        if not samples:
            return AsrResult("", None, 0)
        stream = recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, [sample / 32768.0 for sample in samples])
        recognizer.decode_stream(stream)
        text = (stream.result.text or "").strip()
        # Offline sherpa transducers do not expose a universal confidence
        # field. None means unknown and avoids inventing a confidence score.
        return AsrResult(text, None if text else 0.0, len(samples) * 1000 // self.sample_rate)
