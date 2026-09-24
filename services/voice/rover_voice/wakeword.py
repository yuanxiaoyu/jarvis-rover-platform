from __future__ import annotations

import array
import logging
import re
import time
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)


_JARVIS_ASR_ALIASES = frozenset({
    "贾维斯", "嘉维斯", "甲维斯", "加维斯", "家维斯", "假维斯",
    "贾威斯", "贾为斯", "加威斯", "加为斯", "嘉威斯", "嘉为斯",
    "甲威斯", "甲为斯", "假威斯", "假为斯",
    "亚维斯", "亚威斯", "雅维斯", "雅威斯", "呀维斯", "呀威斯",
    "甲于斯", "甲于此", "加于斯", "嘉于斯", "贾维丝", "贾维司",
})


def _wake_text_matches(phrase: str, text: str) -> bool:
    """Match ASR text conservatively without treating arbitrary speech as wake."""
    compact = re.sub(r"[\s，。！？、,.!?；;：:]+", "", text.strip().lower())
    target = re.sub(r"\s+", "", phrase.strip().lower())
    if not compact or not target:
        return False
    if target in compact:
        return True
    if target == "贾维斯":
        if any(alias in compact for alias in _JARVIS_ASR_ALIASES):
            return True
        return bool(re.search(r"j(?:ar|er|a)?vis", compact))
    return False


class OpenWakeWordDetector:
    """Local openWakeWord detector using an explicitly provisioned model."""

    def __init__(
        self,
        model_path: str,
        threshold: float = 0.5,
        cooldown_seconds: float = 2.0,
        model: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        wakeword_phrase: str = "贾维斯",
    ) -> None:
        self.model_path = model_path
        self.wakeword_phrase = wakeword_phrase.strip()
        if not self.wakeword_phrase:
            raise ValueError("wakeword phrase is required")
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._model = model
        self._last = -float("inf")
        self._clock = clock

    def _score(self, predictions: Mapping[object, object]) -> float:
        """Read only this phrase's score, allowing a model-file label alias."""
        keys: list[object] = [self.wakeword_phrase]
        stem = Path(self.model_path).stem
        if stem and stem not in keys:
            keys.append(stem)
        score = 0.0
        for key in keys:
            value = predictions.get(key, 0.0)
            try:
                score = max(score, float(value))
            except (TypeError, ValueError):
                continue
        return score

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        if not Path(self.model_path).is_file():
            raise FileNotFoundError(self.model_path)
        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError("openWakeWord is unavailable") from exc
        try:
            self._model = Model(wakeword_models=[self.model_path])
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError("openWakeWord model could not be loaded") from exc
        return self._model

    def process(self, frame: bytes) -> bool:
        if len(frame) == 0 or len(frame) % 2:
            raise ValueError("wakeword frame must be non-empty PCM16")
        now = self._clock()
        if now - self._last < self.cooldown_seconds:
            return False
        samples = array.array("h")
        samples.frombytes(frame)
        model = self._load()
        try:
            predictions = model.predict(samples)
            if not isinstance(predictions, Mapping):
                raise ValueError("openWakeWord prediction must be a mapping")
            # A model can expose several keywords. Only the explicitly configured
            # phrase (or its explicitly named model-file label) may arm it.
            score = self._score(predictions)
        except (AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError("openWakeWord prediction failed") from exc
        if score >= self.threshold:
            self._last = now
            return True
        return False


def _keyword_pronunciation(phrase: str) -> str:
    """Return the pinyin/phoneme form expected by the bundled zh KWS model."""
    normalized = phrase.strip()
    if normalized == "贾维斯":
        # The sherpa zh-en KWS token inventory uses an initial/final split and
        # tone-marked pinyin. Keep this explicit so a phrase is never silently
        # accepted with an inaccurate pronunciation.
        return "j iǎ w éi s ī @贾维斯"
    raise ValueError(f"no local KWS pronunciation is provisioned for {normalized!r}")


class SherpaKeywordSpotterDetector:
    """Local streaming sherpa-onnx keyword spotter for Chinese wake phrases."""

    def __init__(
        self,
        model_dir: str,
        threshold: float = 0.25,
        cooldown_seconds: float = 2.0,
        phrase: str = "贾维斯",
        spotter: Any | None = None,
        stream: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        *,
        keywords_file: str = "",
        keywords_score: float = 2.0,
        fallback_asr: Any | None = None,
        fallback_window_seconds: float = 2.5,
        fallback_interval_seconds: float = 2.0,
        fallback_energy_threshold: float = 350.0,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.phrase = phrase.strip()
        if not self.phrase:
            raise ValueError("wakeword phrase is required")
        self._spotter = spotter
        self.keywords_file = Path(keywords_file) if keywords_file else None
        self.keywords_score = float(keywords_score)
        self._fallback_asr = fallback_asr
        self._fallback_interval_seconds = max(0.2, float(fallback_interval_seconds))
        self._fallback_energy_threshold = max(0.0, float(fallback_energy_threshold))
        self._fallback_frames: deque[bytes] = deque(
            maxlen=max(1, round(max(0.5, fallback_window_seconds) * 16000 / 320))
        )
        self._fallback_last = -float("inf")
        self._stream: Any | None = stream
        self._clock = clock
        self._last = -float("inf")

    def _load(self) -> tuple[Any, Any]:
        if self._spotter is not None and self._stream is not None:
            return self._spotter, self._stream
        if not self.model_dir.is_dir():
            raise FileNotFoundError(self.model_dir)
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx is unavailable") from exc

        def one(pattern: str) -> str:
            matches = sorted(self.model_dir.glob(pattern))
            if not matches:
                raise FileNotFoundError(f"KWS model file matching {pattern} is missing")
            # Prefer the quantized model on small ARM hosts when both variants
            # are provisioned; sherpa's decoder/joiner remain interchangeable.
            int8 = [path for path in matches if ".int8." in path.name]
            return str((int8 or matches)[0])

        tokens = self.model_dir / "tokens.txt"
        if not tokens.is_file():
            raise FileNotFoundError(tokens)
        keywords_path = next(
            (path for path in (
                self.keywords_file,
                self.model_dir / "keywords.txt",
                self.model_dir / "test_wavs" / "keywords.txt",
            ) if path is not None and path.is_file()),
            None,
        )
        if keywords_path is None:
            raise FileNotFoundError("KWS keywords.txt is missing")
        try:
            self._spotter = sherpa_onnx.KeywordSpotter(
                tokens=str(tokens),
                encoder=one("*encoder*.onnx"),
                decoder=one("*decoder*.onnx"),
                joiner=one("*joiner*.onnx"),
                keywords_file=str(keywords_path),
                num_threads=1,
                sample_rate=16000,
                feature_dim=80,
                keywords_threshold=self.threshold,
                provider="cpu",
            )
            # The configured file is the source of truth for the wake phrase.
            # For legacy model bundles, append the phrase as an inline keyword
            # with a boost so it can still work without mutating the model tree.
            file_text = keywords_path.read_text(encoding="utf-8", errors="ignore")
            alias = f"@{self.phrase}"
            if alias in file_text:
                self._stream = self._spotter.create_stream()
            else:
                # _keyword_pronunciation already carries the @display-label.
                spec = (
                    f"{_keyword_pronunciation(self.phrase)} "
                    f":{self.keywords_score:g} #{self.threshold:g}"
                )
                self._stream = self._spotter.create_stream(spec)
            logger.info("sherpa KWS loaded phrase=%s keywords_file=%s", self.phrase, keywords_path)
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            raise RuntimeError("sherpa-onnx keyword spotter could not be loaded") from exc
        return self._spotter, self._stream

    def process(self, frame: bytes) -> bool:
        if len(frame) == 0 or len(frame) % 2:
            raise ValueError("wakeword frame must be non-empty PCM16")
        now = self._clock()
        if now - self._last < self.cooldown_seconds:
            return False
        spotter, stream = self._load()
        samples = array.array("h")
        samples.frombytes(frame)
        self._fallback_frames.append(bytes(frame))
        stream.accept_waveform(16000, [sample / 32768.0 for sample in samples])
        detected = False
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            result = str(spotter.get_result(stream) or "").strip()
            if result and (result == self.phrase or self.phrase in result):
                detected = True
                logger.info("wake phrase detected phrase=%s", self.phrase)
                spotter.reset_stream(stream)
                self._fallback_frames.clear()
                break
            if result:
                spotter.reset_stream(stream)
        if detected:
            self._last = now
            return True

        # The bundled KWS model is open-vocabulary, but a short phrase can be
        # missed by a noisy microphone. A bounded local ASR check is a fallback
        # only; it never runs while capturing a command and never sends audio.
        if self._fallback_asr is not None and now - self._fallback_last >= self._fallback_interval_seconds:
            self._fallback_last = now
            window_samples = array.array("h")
            for buffered in self._fallback_frames:
                chunk = array.array("h")
                chunk.frombytes(buffered)
                window_samples.extend(chunk)
            rms = (
                sum(sample * sample for sample in window_samples)
                / max(1, len(window_samples))
            ) ** 0.5
            if rms >= self._fallback_energy_threshold and len(self._fallback_frames) >= 20:
                try:
                    result = self._fallback_asr.transcribe(list(self._fallback_frames))
                    text = str(getattr(result, "text", "") or "")
                    if _wake_text_matches(self.phrase, text):
                        self._last = now
                        self._fallback_frames.clear()
                        logger.info("wake phrase detected by local ASR phrase=%s", self.phrase)
                        return True
                except Exception:
                    # KWS remains the primary detector; ASR fallback failures
                    # must not take the voice service offline.
                    logger.debug("wake ASR fallback unavailable", exc_info=True)
        return False
