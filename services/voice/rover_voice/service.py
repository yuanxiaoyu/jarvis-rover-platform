from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable

from .contracts import AsrResult, VoiceAssistantRequest, VoiceRuntime, VoiceState, VoiceStatus
from .state_machine import StateMachine

logger = logging.getLogger(__name__)


class VoiceService:
    """Local audio conversation loop; it never owns ROS or the provider key."""

    def __init__(self, config, audio_input, wakeword, asr, tts, gateway, clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self.audio_input = audio_input
        self.wakeword = wakeword
        self.asr = asr
        self.tts = tts
        self.gateway = gateway
        self.machine = StateMachine()
        self.runtime: VoiceRuntime = self.machine.runtime
        frame_samples = getattr(config, "frame_samples", 320)
        frame_limit = min(
            max(1, int(config.record_max_seconds * config.sample_rate / frame_samples)),
            getattr(config, "max_audio_queue_frames", 750),
        )
        self.frames: deque[bytes] = deque(maxlen=frame_limit)
        self.running = False
        self.stop_event = threading.Event()
        self._clock = clock
        self._capture_started = 0.0
        self._silence_started = 0.0
        self._followup_until = 0.0
        self._pending_task: asyncio.Task[None] | None = None
        self._wake_ack_pending = False
        self._heartbeat_at = 0.0
        self._tts_poll_at = 0.0
        self._transcript: AsrResult | None = None
        self._latency_asr: float | None = None
        self._latency_assistant: float | None = None
        self._latency_tts: float | None = None

    def enable(self) -> None:
        self.stop_event.clear()
        if self.runtime.state is VoiceState.DISABLED:
            self._set_state(VoiceState.WAKE_LISTENING)
        elif self.runtime.state is not VoiceState.WAKE_LISTENING:
            self.machine.runtime.state = VoiceState.WAKE_LISTENING
            self.machine.runtime.state_changed_at = self._clock()
        self.runtime.session_id = None
        self.runtime.turn_id = None
        self.runtime.last_error = None
        self.frames.clear()
        self._followup_until = 0.0
        self._wake_ack_pending = False

    def transition(self, next_state: VoiceState) -> None:
        self._set_state(next_state)

    def _set_state(self, next_state: VoiceState, error: dict[str, object] | None = None) -> None:
        self.machine.transition(next_state)
        self.runtime.last_error = error
        self.runtime.state_changed_at = self._clock()

    def process_frame(self, frame: bytes) -> None:
        """Process one PCM frame without persisting or uploading raw audio."""
        if not isinstance(frame, bytes) or not frame:
            return
        now = self._clock()
        if self.runtime.state is VoiceState.WAKE_LISTENING:
            try:
                detected = self.wakeword.process(frame)
            except Exception as exc:
                self._fail(VoiceState.AUDIO_UNAVAILABLE, "wakeword_unavailable", exc)
                return
            if detected:
                self.runtime.session_id = uuid.uuid4().hex
                self.runtime.turn_id = None
                self.frames.clear()
                self._capture_started = now
                self._silence_started = 0.0
                # Give the user immediate local feedback.  The acknowledgement
                # is synthesized asynchronously so capture remains responsive;
                # speaking during it interrupts the acknowledgement and starts
                # the command capture.
                self._wake_ack_pending = True
                self.stop_event.clear()
                self._set_state(VoiceState.SPEAKING)
            return

        if self.runtime.state is VoiceState.SPEAKING:
            # Keep VAD running while TTS is playing.  A spoken reply must be
            # interruptible without waiting for the synthesizer to finish.
            try:
                speaking = bool(self.asr.is_speech(frame))
            except Exception:
                # Do not tear down an otherwise healthy playback stream because
                # one VAD frame was malformed; the adapter will report a TTS
                # failure if the playback process itself becomes unhealthy.
                logger.debug("voice VAD unavailable while speaking", exc_info=True)
                return
            if speaking:
                self.interrupt_speaking()
                self._wake_ack_pending = False
                self.frames.clear()
                self.frames.append(bytes(frame))
                self._capture_started = now
                self._silence_started = 0.0
            return

        if self.runtime.state is not VoiceState.CAPTURING:
            return
        self.frames.append(bytes(frame))
        try:
            speaking = bool(self.asr.is_speech(frame))
        except Exception as exc:
            self._fail(VoiceState.ASR_ERROR, "vad_error", exc)
            return
        if speaking:
            self._silence_started = 0.0
        elif not self._silence_started:
            self._silence_started = now
        silence_limit = getattr(self.config, "vad_silence_ms", 700) / 1000.0
        max_duration = getattr(self.config, "record_max_seconds", 15.0)
        if ((self._silence_started and now - self._silence_started >= silence_limit)
                or now - self._capture_started >= max_duration
                or len(self.frames) == self.frames.maxlen):
            self._set_state(VoiceState.PROCESSING_ASR)

    async def run_pending_once(self) -> None:
        if self._wake_ack_pending and self.runtime.state is VoiceState.SPEAKING:
            self._wake_ack_pending = False
            await self._speak_wake_ack()
            return

        if self.runtime.state is VoiceState.PROCESSING_ASR:
            frames = list(self.frames)
            self.frames.clear()
            try:
                started = self._clock()
                result: AsrResult = await asyncio.to_thread(self.asr.transcribe, frames)
                self._latency_asr = (self._clock() - started) * 1000
            except Exception as exc:
                self._fail(VoiceState.ASR_ERROR, "asr_unavailable", exc)
                await self._heartbeat()
                return
            if not result.text.strip() or (result.confidence is not None and result.confidence < getattr(self.config, "min_confidence", 0.35)):
                self._set_state(VoiceState.CAPTURING)
                self._followup_until = self._clock() + getattr(self.config, "followup_seconds", 8.0)
                await self._speak_local("没有听清，请再说一次。")
                return
            self.runtime.turn_id = uuid.uuid4().hex
            self._transcript = result
            self._set_state(VoiceState.PROCESSING_ASSISTANT)
            await self._heartbeat()
            return

        if self.runtime.state is not VoiceState.PROCESSING_ASSISTANT or self._transcript is None:
            return
        request = VoiceAssistantRequest(
            session_id=self.runtime.session_id or uuid.uuid4().hex,
            turn_id=self.runtime.turn_id or uuid.uuid4().hex,
            transcript=self._transcript.text[:1000],
            confidence=self._transcript.confidence,
        )
        try:
            started = self._clock()
            response = await self.gateway.assistant(request)
            self._latency_assistant = (self._clock() - started) * 1000
        except Exception as exc:
            self._fail(VoiceState.ASSISTANT_UNAVAILABLE, "assistant_unavailable", exc)
            await self._speak_local("助手服务暂时不可用。")
            return
        if getattr(response, "state", "completed") == "unavailable":
            self._fail(VoiceState.ASSISTANT_UNAVAILABLE, "assistant_unavailable", None)
            await self._speak_local("助手服务暂时不可用。")
            return
        reply_text = getattr(response, "reply_text", "")
        if not isinstance(reply_text, str) or not reply_text.strip():
            self._fail(VoiceState.ASSISTANT_UNAVAILABLE, "empty_response", None)
            await self._heartbeat()
            return
        self._set_state(VoiceState.SPEAKING)
        self.stop_event.clear()
        await self._heartbeat()
        try:
            started = self._clock()
            await asyncio.to_thread(self.tts.speak, reply_text[:2000], self.stop_event)
            self._latency_tts = (self._clock() - started) * 1000
        except Exception as exc:
            self._fail(VoiceState.TTS_ERROR, "tts_unavailable", exc)
            await self._heartbeat()
            self._set_state(VoiceState.WAKE_LISTENING)
            await self._heartbeat()
            return
        if not self.stop_event.is_set():
            self._set_state(VoiceState.CAPTURING)
            self._followup_until = self._clock() + getattr(self.config, "followup_seconds", 8.0)
        await self._heartbeat()

    def run_pending_once_sync(self) -> None:
        asyncio.run(self.run_pending_once())

    async def run(self) -> None:
        self.running = True
        self.enable()
        try:
            async for frame in self.audio_input.start():
                if not self.running:
                    break
                self.process_frame(frame)
                if (
                    self.runtime.state in {VoiceState.PROCESSING_ASR, VoiceState.PROCESSING_ASSISTANT}
                    or self._wake_ack_pending
                ) and self._pending_task is None:
                    self._pending_task = asyncio.create_task(self.run_pending_once())
                if self._pending_task and self._pending_task.done():
                    self._pending_task = None
                if self._followup_until and self._clock() >= self._followup_until and self.runtime.state is VoiceState.CAPTURING:
                    self._set_state(VoiceState.WAKE_LISTENING)
                    self._followup_until = 0.0
                if self.runtime.state is VoiceState.WAKE_LISTENING and self._clock() - self._tts_poll_at >= 0.5:
                    self._tts_poll_at = self._clock()
                    next_tts = getattr(self.gateway, "next_tts", None)
                    if next_tts is not None:
                        queued_text = await next_tts()
                        if queued_text:
                            self._set_state(VoiceState.SPEAKING)
                            await self._heartbeat()
                            try:
                                await asyncio.to_thread(self.tts.speak, queued_text[:2000], self.stop_event)
                            except Exception as exc:
                                self._fail(VoiceState.TTS_ERROR, "tts_unavailable", exc)
                                await self._heartbeat()
                            finally:
                                if self.runtime.state in {VoiceState.SPEAKING, VoiceState.TTS_ERROR}:
                                    self._set_state(VoiceState.WAKE_LISTENING)
                                    await self._heartbeat()
                if self._clock() - self._heartbeat_at >= getattr(self.config, "heartbeat_interval_seconds", 3.0):
                    await self._heartbeat()
        except Exception as exc:
            self._fail(VoiceState.AUDIO_UNAVAILABLE, "audio_unavailable", exc)
            await self._heartbeat()
        finally:
            await self._close_adapters()

    async def _speak_local(self, text: str) -> None:
        self.stop_event.clear()
        try:
            started = self._clock()
            await asyncio.to_thread(self.tts.speak, text, self.stop_event)
            self._latency_tts = (self._clock() - started) * 1000
        except Exception as exc:
            self._fail(VoiceState.TTS_ERROR, "tts_unavailable", exc)
        if self.runtime.state in {VoiceState.ASR_ERROR, VoiceState.ASSISTANT_UNAVAILABLE, VoiceState.TTS_ERROR}:
            self._set_state(VoiceState.WAKE_LISTENING)
        await self._heartbeat()

    async def _speak_wake_ack(self) -> None:
        text = str(getattr(self.config, "wake_ack_text", "我在，请说。") or "我在，请说。").strip()
        if not text:
            self._set_state(VoiceState.CAPTURING)
            self._followup_until = self._clock() + getattr(self.config, "followup_seconds", 8.0)
            return
        try:
            started = self._clock()
            await asyncio.to_thread(self.tts.speak, text, self.stop_event)
            self._latency_tts = (self._clock() - started) * 1000
        except Exception as exc:
            self._fail(VoiceState.TTS_ERROR, "tts_unavailable", exc)
            self._set_state(VoiceState.WAKE_LISTENING)
            await self._heartbeat()
            return
        if self.runtime.state is VoiceState.SPEAKING and not self.stop_event.is_set():
            self._set_state(VoiceState.CAPTURING)
            self._capture_started = self._clock()
            self._silence_started = 0.0
            self._followup_until = self._clock() + getattr(self.config, "followup_seconds", 8.0)
        await self._heartbeat()

    async def _heartbeat(self) -> None:
        self._heartbeat_at = self._clock()
        status = VoiceStatus(
            state=self.runtime.state,
            enabled=self.runtime.state is not VoiceState.DISABLED,
            session_id=self.runtime.session_id,
            turn_id=self.runtime.turn_id,
            last_error=self.runtime.last_error,
            component_latency_ms={
                "asr": self._latency_asr,
                "assistant": self._latency_assistant,
                "tts": self._latency_tts,
            },
        )
        try:
            await self.gateway.heartbeat(status)
        except Exception:
            logger.debug("voice heartbeat unavailable", exc_info=True)

    def _fail(self, state: VoiceState, code: str, exc: Exception | None) -> None:
        safe_code = {
            VoiceState.AUDIO_UNAVAILABLE: "audio_unavailable",
            VoiceState.ASR_ERROR: "asr_error",
            VoiceState.ASSISTANT_UNAVAILABLE: "assistant_unavailable",
            VoiceState.TTS_ERROR: "tts_error",
        }.get(state, code)
        logger.warning(
            "voice component failure code=%s error_type=%s",
            code,
            type(exc).__name__ if exc is not None else "none",
        )
        self._set_state(state, {"code": safe_code, "message": safe_code, "recoverable": True})

    async def _close_adapters(self) -> None:
        for adapter in (self.audio_input, self.gateway):
            close = getattr(adapter, "close", None)
            if close is not None:
                value = close()
                if asyncio.iscoroutine(value):
                    await value

    def stop(self) -> None:
        self.running = False
        self.stop_event.set()
        if self._pending_task and not self._pending_task.done():
            self._pending_task.cancel()

    def interrupt_speaking(self) -> None:
        self.stop_event.set()
        self._wake_ack_pending = False
        if self.runtime.state is VoiceState.SPEAKING:
            self._set_state(VoiceState.CAPTURING)
            self._followup_until = self._clock() + getattr(self.config, "followup_seconds", 8.0)
