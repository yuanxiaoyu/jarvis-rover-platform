from __future__ import annotations

import os
import shutil
import signal
import struct
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class PocketTtsError(RuntimeError):
    """Safe, user-facing category for local TTS and playback failures."""


def _terminate_process(process: Any) -> None:
    if getattr(process, "poll", lambda: 0)() is not None:
        return
    try:
        pid = process.pid
        os.killpg(pid, signal.SIGTERM)
    except (AttributeError, ProcessLookupError, PermissionError):
        try:
            process.terminate()
        except (AttributeError, OSError):
            return
    try:
        process.wait(timeout=1)
    except (AttributeError, subprocess.TimeoutExpired, OSError):
        try:
            process.kill()
        except (AttributeError, OSError):
            pass


class _StreamingLinearResampler:
    """Bounded linear resampler that keeps continuity across generated chunks."""

    def __init__(self, source_rate: int, target_rate: int) -> None:
        self.source_rate = source_rate
        self.target_rate = target_rate
        self._step = source_rate / target_rate if source_rate != target_rate else 1.0
        self._buffer: list[float] = []
        self._position = 0.0

    def push(self, samples: list[float], *, final: bool = False) -> list[float]:
        if self.source_rate == self.target_rate:
            return samples
        if samples:
            self._buffer.extend(samples)
        if not self._buffer:
            return []

        output: list[float] = []
        sample_count = len(self._buffer)
        # While streaming, retain the final source sample so the next chunk can
        # interpolate across the boundary. At the end, hold the final sample
        # for the few output positions needed to preserve the duration.
        limit = float(sample_count) if final else float(max(0, sample_count - 1))
        while self._position < limit:
            left = min(int(self._position), sample_count - 1)
            right = min(left + 1, sample_count - 1)
            fraction = self._position - left
            output.append(self._buffer[left] + (self._buffer[right] - self._buffer[left]) * fraction)
            self._position += self._step

        if final:
            self._buffer.clear()
            self._position = 0.0
            return output

        # Keep one sample before the next interpolation point and discard the
        # rest so memory remains bounded even for long replies.
        discard = max(0, int(self._position) - 1)
        if discard:
            del self._buffer[:discard]
            self._position -= discard
        return output


class _PcmPlayback:
    """One bounded aplay process fed incrementally by a TTS generator."""

    def __init__(
        self,
        device: str,
        sample_rate: int,
        playback_factory: Callable[..., Any],
        command_exists: Callable[[str], str | None],
        max_audio_seconds: float,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self._playback_factory = playback_factory
        self._command_exists = command_exists
        self._max_samples = int(sample_rate * max_audio_seconds)
        self._process: Any | None = None
        self.total_samples = 0

    @property
    def process(self) -> Any | None:
        return self._process

    def start(self) -> None:
        if self._command_exists("aplay") is None:
            raise PocketTtsError("aplay is unavailable")
        if not self.device:
            raise PocketTtsError("playback device is not configured")
        args = [
            "aplay", "-q", "-D", self.device, "-f", "S16_LE",
            "-r", str(self.sample_rate), "-c", "1", "-t", "raw", "-",
        ]
        self._process = self._playback_factory(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        if getattr(self._process, "stdin", None) is None:
            self.abort()
            raise PocketTtsError("aplay stdin is unavailable")

    def write(self, samples: list[float], stop_event) -> bool:
        if not samples:
            return not stop_event.is_set()
        if self._process is None:
            raise PocketTtsError("aplay is not started")
        if self.total_samples + len(samples) > self._max_samples:
            raise PocketTtsError("TTS audio exceeds configured limit")
        stdin = self._process.stdin
        try:
            for offset in range(0, len(samples), 2048):
                if stop_event.is_set():
                    self.abort()
                    return False
                stdin.write(_pcm16(samples[offset : offset + 2048]))
                flush = getattr(stdin, "flush", None)
                if flush is not None:
                    flush()
            self.total_samples += len(samples)
            return True
        except (BrokenPipeError, OSError) as exc:
            self.abort()
            raise PocketTtsError("audio playback failed") from exc

    def finish(self, stop_event, *, timeout_seconds: float) -> None:
        process = self._process
        if process is None:
            return
        try:
            if stop_event.is_set():
                self.abort()
                return
            process.stdin.close()
            return_code = process.wait(timeout=timeout_seconds)
            if return_code != 0 and not stop_event.is_set():
                raise PocketTtsError("audio playback failed")
        except subprocess.TimeoutExpired as exc:
            self.abort()
            raise PocketTtsError("audio playback timed out") from exc
        except (BrokenPipeError, OSError) as exc:
            self.abort()
            raise PocketTtsError("audio playback failed") from exc
        finally:
            if getattr(process, "poll", lambda: None)() is None:
                _terminate_process(process)
            self._process = None

    def abort(self) -> None:
        process = self._process
        if process is not None:
            _terminate_process(process)
            self._process = None


def _pcm16(samples: Iterable[float]) -> bytes:
    values = []
    for sample in samples:
        value = max(-1.0, min(1.0, float(sample)))
        values.append(max(-32768, min(32767, round(value * 32767))))
    return struct.pack("<" + "h" * len(values), *values)


class _PcmPlayerMixin:
    playback_device: str
    playback_sample_rate: int
    _playback_factory: Callable[..., Any]
    _command_exists: Callable[[str], str | None]
    max_audio_seconds: float
    _playback: Any | None

    def _new_playback(self) -> _PcmPlayback:
        return _PcmPlayback(
            self.playback_device,
            self.playback_sample_rate,
            self._playback_factory,
            self._command_exists,
            self.max_audio_seconds,
        )

    def _play_complete(self, samples: list[float], stop_event) -> None:
        playback = self._new_playback()
        try:
            playback.start()
            self._playback = playback.process
            playback.write(samples, stop_event)
            playback.finish(
                stop_event,
                timeout_seconds=min(
                    self.max_audio_seconds + 5.0,
                    max(5.0, len(samples) / self.playback_sample_rate + 5.0),
                ),
            )
        finally:
            playback.abort()
            self._playback = None


class PocketTtsPlayer(_PcmPlayerMixin):
    """Offline Pocket TTS player with first-chunk streaming on CPU hosts."""

    def __init__(
        self,
        model_dir: str,
        checkpoint: str,
        voice_state: str,
        playback_device: str,
        device: str = "cpu",
        playback_sample_rate: int = 24000,
        model_loader: Callable[..., Any] | None = None,
        playback_factory: Callable[..., Any] | None = None,
        command_exists: Callable[[str], str | None] = shutil.which,
        max_audio_seconds: float = 60.0,
        config_path: str = "",
    ) -> None:
        self.model_dir = Path(model_dir)
        self.checkpoint = Path(checkpoint)
        self.voice_state_path = Path(voice_state)
        self.playback_device = playback_device
        self.device = device
        self.playback_sample_rate = playback_sample_rate
        self._model_loader = model_loader
        self._playback_factory = playback_factory or subprocess.Popen
        self._command_exists = command_exists
        self.max_audio_seconds = max_audio_seconds
        self.config_path = Path(config_path) if config_path else None
        self._model: Any | None = None
        self._voice: Any | None = None
        self._playback: Any | None = None

    def speak(self, text: str, stop_event) -> None:
        if not text or not text.strip():
            return
        self._validate()
        model = self._load_model()
        stream = getattr(model, "generate_audio_stream", None)
        if callable(stream):
            self._speak_stream(model, stream, text.strip(), stop_event)
            return
        self._speak_complete(model, text.strip(), stop_event)

    def _speak_stream(self, model: Any, stream: Callable[..., Iterator[Any]], text: str, stop_event) -> None:
        if stop_event.is_set():
            return
        playback = self._new_playback()
        source_rate: int | None = None
        source_samples = 0
        resampler: _StreamingLinearResampler | None = None
        try:
            playback.start()
            self._playback = playback.process
            chunks = stream(model_state=self._voice, text_to_generate=text)
            for chunk in chunks:
                if stop_event.is_set():
                    return
                samples, chunk_rate = self._audio_samples(chunk, model)
                if not samples:
                    continue
                if source_rate is None:
                    source_rate = chunk_rate
                    resampler = _StreamingLinearResampler(source_rate, self.playback_sample_rate)
                elif chunk_rate != source_rate:
                    raise PocketTtsError("Pocket TTS returned inconsistent sample rates")
                source_samples += len(samples)
                if source_rate and source_samples > int(source_rate * self.max_audio_seconds):
                    raise PocketTtsError("Pocket TTS audio exceeds configured limit")
                assert resampler is not None
                if not playback.write(resampler.push(samples), stop_event):
                    return
            if source_rate is None or source_samples == 0:
                raise PocketTtsError("Pocket TTS returned empty audio")
            assert resampler is not None
            if not playback.write(resampler.push([], final=True), stop_event):
                return
            playback.finish(
                stop_event,
                timeout_seconds=min(
                    self.max_audio_seconds + 5.0,
                    max(5.0, playback.total_samples / self.playback_sample_rate + 5.0),
                ),
            )
        except PocketTtsError:
            raise
        except Exception as exc:
            raise PocketTtsError("Pocket TTS synthesis failed") from exc
        finally:
            playback.abort()
            self._playback = None

    def _speak_complete(self, model: Any, text: str, stop_event) -> None:
        try:
            audio = model.generate_audio(self._voice, text)
            samples, source_rate = self._audio_samples(audio, model)
        except Exception as exc:
            raise PocketTtsError("Pocket TTS synthesis failed") from exc
        if not samples:
            raise PocketTtsError("Pocket TTS returned empty audio")
        if len(samples) > int(source_rate * self.max_audio_seconds):
            raise PocketTtsError("Pocket TTS audio exceeds configured limit")
        if source_rate != self.playback_sample_rate:
            samples = self._resample(samples, source_rate, self.playback_sample_rate)
        if len(samples) > int(self.playback_sample_rate * self.max_audio_seconds):
            raise PocketTtsError("resampled audio exceeds configured limit")
        if stop_event.is_set():
            return
        self._play_complete(samples, stop_event)

    def _validate(self) -> None:
        if not self.model_dir.is_dir():
            raise FileNotFoundError(f"Pocket TTS model directory missing: {self.model_dir}")
        if not self.checkpoint.is_file():
            raise FileNotFoundError(f"Pocket TTS checkpoint missing: {self.checkpoint}")
        if not self.voice_state_path.is_file():
            raise FileNotFoundError(f"Pocket TTS voice state missing: {self.voice_state_path}")
        if not self.playback_device:
            raise PocketTtsError("playback device is not configured")
        if self.device != "cpu":
            raise PocketTtsError("Pocket TTS supports CPU execution on the Pi 5 profile")
        if self.playback_sample_rate <= 0 or self.max_audio_seconds <= 0:
            raise PocketTtsError("Pocket TTS playback limits are invalid")

    @contextmanager
    def _local_model_config(self):
        config_path = self.config_path or (self.model_dir / "config.yaml")
        if not config_path.is_file():
            raise FileNotFoundError(f"Pocket TTS local config missing: {config_path}")
        try:
            import yaml
        except ImportError as exc:
            raise PocketTtsError("Pocket TTS YAML support is unavailable") from exc
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise PocketTtsError("Pocket TTS local config could not be read") from exc
        if not isinstance(data, dict):
            raise PocketTtsError("Pocket TTS local config is invalid")

        data["weights_path"] = str(self.checkpoint)
        data["weights_path_without_voice_cloning"] = str(self.checkpoint)
        flow_lm = data.get("flow_lm")
        lookup = flow_lm.get("lookup_table") if isinstance(flow_lm, dict) else None
        if isinstance(lookup, dict):
            tokenizer = str(lookup.get("tokenizer_path", ""))
            if tokenizer.startswith(("hf://", "http://", "https://")):
                local_tokenizer = self.model_dir / "tokenizer.model"
                if not local_tokenizer.is_file():
                    raise PocketTtsError("Pocket TTS local tokenizer.model is missing")
                lookup["tokenizer_path"] = str(local_tokenizer)

        def contains_remote(value: Any) -> bool:
            if isinstance(value, str):
                return value.startswith(("hf://", "http://", "https://"))
            if isinstance(value, dict):
                return any(contains_remote(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_remote(item) for item in value)
            return False

        if contains_remote(data):
            raise PocketTtsError("Pocket TTS config contains a remote asset")
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", suffix=".yaml", prefix="jarvis-pocket-", delete=False
            ) as handle:
                yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
                temp_path = Path(handle.name)
            yield temp_path
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_model(self) -> Any:
        if self._model is not None and self._voice is not None:
            return self._model
        if self._model_loader is not None:
            try:
                self._model = self._model_loader(checkpoint=str(self.checkpoint), device=self.device)
            except (TypeError, OSError, ValueError, RuntimeError) as exc:
                raise PocketTtsError("Pocket TTS loader does not support the local checkpoint") from exc
        else:
            try:
                from pocket_tts import TTSModel
            except ImportError as exc:
                raise PocketTtsError("pocket-tts is unavailable") from exc
            try:
                with self._local_model_config() as config_path:
                    # Pocket TTS 1.1 loads CPU weights through a local YAML
                    # config; it has no checkpoint= or device= keyword.
                    self._model = TTSModel.load_model(config=str(config_path))
            except PocketTtsError:
                raise
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                raise PocketTtsError("Pocket TTS local model could not be loaded") from exc
        get_voice = getattr(self._model, "get_state_for_audio_prompt", None)
        if get_voice is None:
            raise PocketTtsError("Pocket TTS voice-state API is unavailable")
        try:
            self._voice = get_voice(str(self.voice_state_path))
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            raise PocketTtsError("Pocket TTS voice state could not be loaded") from exc
        return self._model

    @staticmethod
    def _audio_samples(audio: Any, model: Any) -> tuple[list[float], int]:
        source_rate = int(getattr(audio, "sample_rate", getattr(model, "sample_rate", 24000)))
        values: Any = getattr(audio, "samples", audio)
        if hasattr(values, "detach"):
            values = values.detach()
        if hasattr(values, "cpu"):
            values = values.cpu()
        if hasattr(values, "flatten"):
            values = values.flatten()
        if hasattr(values, "tolist"):
            values = values.tolist()
        if isinstance(values, (int, float)):
            values = [values]
        try:
            samples = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise PocketTtsError("Pocket TTS returned an unsupported audio type") from exc
        if source_rate <= 0:
            raise PocketTtsError("Pocket TTS returned an invalid sample rate")
        return samples, source_rate

    @staticmethod
    def _resample(samples: list[float], source_rate: int, target_rate: int) -> list[float]:
        if source_rate == target_rate or len(samples) < 2:
            return samples
        target_length = max(1, round(len(samples) * target_rate / source_rate))
        result: list[float] = []
        scale = (len(samples) - 1) / max(1, target_length - 1)
        for index in range(target_length):
            position = index * scale
            left = min(int(position), len(samples) - 1)
            right = min(left + 1, len(samples) - 1)
            fraction = position - left
            result.append(samples[left] + (samples[right] - samples[left]) * fraction)
        return result

    @staticmethod
    def _pcm16(samples: Iterable[float]) -> bytes:
        return _pcm16(samples)

    @staticmethod
    def _terminate(process: Any) -> None:
        _terminate_process(process)


class SherpaVitsTtsPlayer(_PcmPlayerMixin):
    """Local Mandarin sherpa-onnx VITS player for ARM hosts."""

    def __init__(
        self,
        model_dir: str,
        playback_device: str,
        device: str = "cpu",
        playback_sample_rate: int = 24000,
        speaker_id: int = 21,
        rule_fsts: str = "",
        tts_factory: Callable[..., Any] | None = None,
        playback_factory: Callable[..., Any] | None = None,
        command_exists: Callable[[str], str | None] = shutil.which,
        max_audio_seconds: float = 60.0,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.playback_device = playback_device
        self.device = device
        self.playback_sample_rate = playback_sample_rate
        self.speaker_id = speaker_id
        self.rule_fsts = rule_fsts
        self._tts_factory = tts_factory
        self._playback_factory = playback_factory or subprocess.Popen
        self._command_exists = command_exists
        self.max_audio_seconds = max_audio_seconds
        self._tts: Any | None = None
        self._playback: Any | None = None

    def speak(self, text: str, stop_event) -> None:
        if not text or not text.strip():
            return
        self._validate()
        tts = self._load()
        try:
            import sherpa_onnx

            generation = sherpa_onnx.GenerationConfig()
            generation.sid = self.speaker_id
            generation.speed = 1.0
        except (AttributeError, ImportError, TypeError, ValueError) as exc:
            raise PocketTtsError("sherpa VITS synthesis is unavailable") from exc

        playback = self._new_playback()
        callback_samples = 0
        source_rate: int | None = None
        source_total = 0
        resampler: _StreamingLinearResampler | None = None
        callback_used = False

        def on_chunk(chunk: Any, _progress: float) -> int:
            nonlocal callback_samples, source_rate, source_total, resampler
            if stop_event.is_set():
                playback.abort()
                return 1
            samples, chunk_rate = self._audio_samples(chunk, tts)
            if not samples:
                return 0
            if source_rate is None:
                source_rate = chunk_rate
                resampler = _StreamingLinearResampler(source_rate, self.playback_sample_rate)
            elif source_rate != chunk_rate:
                raise PocketTtsError("sherpa VITS returned inconsistent sample rates")
            source_total += len(samples)
            if source_rate and source_total > int(source_rate * self.max_audio_seconds):
                raise PocketTtsError("sherpa VITS audio exceeds configured limit")
            assert resampler is not None
            output = resampler.push(samples)
            if output and not playback.write(output, stop_event):
                return 1
            callback_samples += len(samples)
            return 0

        try:
            if stop_event.is_set():
                return
            playback.start()
            self._playback = playback.process
            try:
                audio = tts.generate(text.strip(), generation, callback=on_chunk)
                callback_used = True
            except TypeError:
                # sherpa-onnx versions before callback support and lightweight
                # test doubles still expose the complete-audio overload.
                playback.abort()
                self._playback = None
                playback = self._new_playback()
                playback.start()
                self._playback = playback.process
                audio = tts.generate(text.strip(), generation)

            if stop_event.is_set():
                return
            if callback_used and callback_samples:
                assert resampler is not None
                if not playback.write(resampler.push([], final=True), stop_event):
                    return
            else:
                samples, complete_rate = self._audio_samples(audio, tts)
                if not samples:
                    raise PocketTtsError("sherpa VITS returned empty audio")
                if len(samples) > int(complete_rate * self.max_audio_seconds):
                    raise PocketTtsError("sherpa VITS audio exceeds configured limit")
                if complete_rate != self.playback_sample_rate:
                    samples = PocketTtsPlayer._resample(samples, complete_rate, self.playback_sample_rate)
                if len(samples) > int(self.playback_sample_rate * self.max_audio_seconds):
                    raise PocketTtsError("resampled audio exceeds configured limit")
                playback.write(samples, stop_event)
            playback.finish(
                stop_event,
                timeout_seconds=min(
                    self.max_audio_seconds + 5.0,
                    max(5.0, playback.total_samples / self.playback_sample_rate + 5.0),
                ),
            )
        except PocketTtsError:
            raise
        except Exception as exc:
            raise PocketTtsError("sherpa VITS synthesis failed") from exc
        finally:
            playback.abort()
            self._playback = None

    def _validate(self) -> None:
        if self.device != "cpu":
            raise PocketTtsError("sherpa VITS supports only CPU execution")
        if not self.model_dir.is_dir():
            raise FileNotFoundError(f"sherpa VITS model directory missing: {self.model_dir}")
        for name in ("model.onnx", "lexicon.txt", "tokens.txt"):
            if not (self.model_dir / name).is_file():
                raise FileNotFoundError(f"sherpa VITS model file missing: {self.model_dir / name}")
        if not self.playback_device:
            raise PocketTtsError("playback device is not configured")
        if self.playback_sample_rate <= 0 or self.max_audio_seconds <= 0:
            raise PocketTtsError("sherpa VITS playback limits are invalid")

    def _load(self) -> Any:
        if self._tts is not None:
            return self._tts
        factory = self._tts_factory
        if factory is None:
            try:
                import sherpa_onnx
            except ImportError as exc:
                raise PocketTtsError("sherpa-onnx is unavailable") from exc
            vits = sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(self.model_dir / "model.onnx"),
                lexicon=str(self.model_dir / "lexicon.txt"),
                tokens=str(self.model_dir / "tokens.txt"),
            )
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=vits, provider="cpu", num_threads=2,
                ),
                rule_fsts=self.rule_fsts,
                max_num_sentences=1,
            )
            if not config.validate():
                raise PocketTtsError("sherpa VITS configuration is invalid")
            factory = sherpa_onnx.OfflineTts
            self._tts = factory(config)
        else:
            self._tts = factory(
                model=str(self.model_dir / "model.onnx"),
                lexicon=str(self.model_dir / "lexicon.txt"),
                tokens=str(self.model_dir / "tokens.txt"),
                rule_fsts=self.rule_fsts,
                device=self.device,
            )
        return self._tts

    @staticmethod
    def _audio_samples(audio: Any, tts: Any) -> tuple[list[float], int]:
        return PocketTtsPlayer._audio_samples(audio, tts)
