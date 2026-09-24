from __future__ import annotations

import array
from pathlib import Path
from typing import Any

from .contracts import AsrResult


class SherpaOnnxRecognizer:
    """Lazy offline sherpa-onnx recognizer for locally buffered PCM16 frames."""

    def __init__(self, model_dir: str, min_confidence: float = 0.35, sample_rate: int = 16000, recognizer: Any | None = None):
        self.model_dir = model_dir
        self.min_confidence = min_confidence
        self.sample_rate = sample_rate
        self._recognizer = recognizer

    def _load(self) -> Any:
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
            # The provisioned Zipformer model is streaming; using the offline
            # recognizer would fail with an input feature-dimension mismatch.
            self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                encoder=one("*encoder*.onnx"), decoder=one("*decoder*.onnx"),
                joiner=one("*joiner*.onnx"), tokens=one("tokens.txt"),
                num_threads=1, sample_rate=self.sample_rate, feature_dim=80,
                decoding_method="greedy_search",
            )
        except (AttributeError, TypeError, ValueError, OSError) as exc:
            raise RuntimeError("unsupported sherpa-onnx transducer model") from exc
        return self._recognizer

    @staticmethod
    def _samples(frame: bytes) -> array.array[int]:
        if len(frame) % 2:
            raise ValueError("ASR frame must contain PCM16 samples")
        samples = array.array("h")
        samples.frombytes(frame)
        return samples

    def is_speech(self, frame: bytes) -> bool:
        samples = self._samples(frame)
        if not samples:
            return False
        # Conservative local VAD. A sherpa VAD can replace this implementation
        # without changing the service contract.
        return sum(abs(sample) for sample in samples) / len(samples) > 350

    def transcribe(self, frames: list[bytes]) -> AsrResult:
        if not frames:
            return AsrResult("", None, 0)
        recognizer = self._load()
        samples = array.array("h")
        for frame in frames:
            samples.extend(self._samples(frame))
        if not samples:
            return AsrResult("", None, 0)
        stream = recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, [sample / 32768.0 for sample in samples])
        # Flush the streaming encoder so short utterances are decoded before
        # the stream is discarded.
        if hasattr(stream, "input_finished"):
            stream.accept_waveform(self.sample_rate, [0.0] * int(self.sample_rate * 0.5))
            stream.input_finished()
        while hasattr(recognizer, "is_ready") and recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        if hasattr(recognizer, "get_result_all"):
            result = recognizer.get_result_all(stream)
            text = (getattr(result, "text", "") or "").strip()
        else:
            result = getattr(stream, "result", None)
            text = (getattr(result, "text", "") or "").strip()
        # sherpa streaming transducers do not expose a universal confidence field.
        return AsrResult(text, None if text else 0.0, len(samples) * 1000 // self.sample_rate)
