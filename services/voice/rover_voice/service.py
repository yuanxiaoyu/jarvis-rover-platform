from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator

from .contracts import (
    AsrResult,
    VoiceAssistantRequest,
    VoiceRuntime,
    VoiceState,
    VoiceStatus,
)
from .state_machine import StateMachine

logger = logging.getLogger(__name__)


class VoiceService:
    """Local audio conversation loop; it never owns ROS or the provider key."""

    def __init__(self, config, audio_input, wakeword, asr, tts, gateway) -> None:
        self.config = config
        self.audio_input = audio_input
        self.wakeword = wakeword
        self.asr = asr
        self.tts = tts
        self.gateway = gateway
        self.machine = StateMachine()
        self.runtime: VoiceRuntime = self.machine.runtime
        frame_limit = min(
            max(1, int(config.record_max_seconds * config.sample_rate / 320)),
            getattr(config, "max_audio_queue_frames", 750),
        )
        self.frames: deque[bytes] = deque(maxlen=frame_limit)
        self.running = False
        self.stop_event = threading.Event()
        self._capture_started = 0.0
        self._last_speech = 0.0
        self._silence_started = 0.0
        self._followup_until = 0.0
        self._pending_task: asyncio.Task[None] | None = None
        self._heartbeat_at = 0.0
        self._sequence = 0

    def enable(self) -> None:
        self.stop_event.clear()
        self._set_state(VoiceState.WAKE_LISTENING)
        self.runtime.session_id = None
        self.runtime.turn_id = None
        self.runtime.last_error = None

    def transition(self, next_state: VoiceState) -> None:
        self._set_state(next_state)

    def _set_state(self, next_state: VoiceState, error: dict[str, object] | None = None) -> None:
        self.machine.transition(next_state)
        self.runtime.last_error = error
        self.runtime.state_changed_at = time.monotonic()

    def process_frame(self, frame: bytes) -> None:
        """Process one PCM frame; this method is deterministic and hardware-free."""
        now = time.monotonic()
        if self.runtime.state == VoiceState.WAKE_LISTENING:
            try:
                detected = self.wakeword.process(frame)
            except Exception as exc:  # adapters convert this to visible health
                self._fail(VoiceState.AUDIO_UNAVAILABLE, "wakeword_unavailable", exc)
                return
            if detected:
                self.runtime.session_id = uuid.uuid4().hex
                self.runtime.turn_id = None
                self.frames.clear()
                self._capture_started = now
                self._last_speech = now
                self._silence_started = 0.0
                self._set_state(VoiceState.CAPTURING)
            return

        if self.runtime.state != VoiceState.CAPTURING:
            return
        self.frames.append(bytes(frame))
        try:
            speaking = bool(self.asr.is_speech(frame))
        except Exception as exc:
            self._fail(VoiceState.ASR_ERROR, "vad_error", exc)
            return
        if speaking:
            self._last_speech = now
            self._silence_started = 0.0
        elif not self._silence_started:
            self._silence_started = now
        silence_limit = getattr(self.config, "vad_silence_ms", 700) / 1000.0
        max_duration = getattr(self.config, "record_max_seconds", 15.0)
        if (self._silence_started and now - self._silence_started >= silence_limit) or now - self._capture_started >= max_duration:
            self._set_state(VoiceState.PROCESSING_ASR)

    async def run_pending_once(self) -> None:
        if self.runtime.state == VoiceState.PROCESSING_ASR:
            frames = list(self.frames)
            self.frames.clear()
            try:
                started = time.monotonic()
                result: AsrResult = await asyncio.to_thread(self.asr.transcribe, frames)
                self._latency_asr = (time.monotonic() - started) * 1000
            except Exception as exc:
                self._fail(VoiceState.ASR_ERROR, "asr_unavailable", exc)
                await self._heartbeat()
                return
            if not result.text.strip() or (result.confidence is not None and result.confidence < getattr(self.config, "min_confidence", 0.35)):
                self._set_state(VoiceState.CAPTURING)
                self._followup_until = time.monotonic() + getattr(self.config, "followup_seconds", 8.0)
                await self._speak_local("没有听清，请再说一次。")
                return
            self.runtime.turn_id = uuid.uuid4().hex
            self._transcript = result
            self._set_state(VoiceState.PROCESSING_ASSISTANT)

        if self.runtime.state != VoiceState.PROCESSING_ASSISTANT:
            return
        result: AsrResult = self._transcript
        request = VoiceAssistantRequest(
            session_id=self.runtime.session_id or uuid.uuid4().hex,
            turn_id=self.runtime.turn_id or uuid.uuid4().hex,
            transcript=result.text[:1000],
            confidence=result.confidence,
        )
        try:
            started = time.monotonic()
            response = await self.gateway.assistant(request)
            self._latency_assistant = (time.monotonic() - started) * 1000
        except Exception as exc:
            self._fail(VoiceState.ASSISTANT_UNAVAILABLE, "assistant_unavailable", exc)
            await self._speak_local("助手服务暂时不可用。")
            return
        if not getattr(response, "reply_text", ""):
            self._fail(VoiceState.ASSISTANT_UNAVAILABLE, "empty_response", None)
            return
        self._set_state(VoiceState.SPEAKING)
        self.stop_event.clear()
        try:
            started = time.monotonic()
            await asyncio.to_thread(self.tts.speak, response.reply_text[:2000], self.stop_event)
            self._latency_tts = (time.monotonic() - started) * 1000
        except Exception as exc:
            self._fail(VoiceState.TTS_ERROR, "tts_unavailable", exc)
            return
        if self.running and not self.stop_event.is_set():
            self._set_state(VoiceState.CAPTURING)
            self._followup_until = time.monotonic() + getattr(self.config, "followup_seconds", 8.0)
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
                if self.runtime.state == VoiceState.PROCESSING_ASR and self._pending_task is None:
                    self._pending_task = asyncio.create_task(self.run_pending_once())
                elif self.runtime.state == VoiceState.PROCESSING_ASSISTANT and self._pending_task is None:
                    self._pending_task = asyncio.create_task(self.run_pending_once())
                if self._pending_task and self._pending_task.done():
                    self._pending_task = None
                if time.monotonic() >= self._followup_until and self.runtime.state == VoiceState.CAPTURING and self._followup_until:
                    self._set_state(VoiceState.WAKE_LISTENING)
                    self._followup_until = 0.0
                if time.monotonic() - self._heartbeat_at >= 2.0:
                    await self._heartbeat()
        except Exception as exc:
            self._fail(VoiceState.AUDIO_UNAVAILABLE, "audio_unavailable", exc)
            await self._heartbeat()
        finally:
            await self._close_adapters()

    async def _speak_local(self, text: str) -> None:
        self.stop_event.clear()
        try:
            await asyncio.to_thread(self.tts.speak, text, self.stop_event)
        except Exception as exc:
            self._fail(VoiceState.TTS_ERROR, "tts_unavailable", exc)
        await self._heartbeat()

    async def _heartbeat(self) -> None:
        self._heartbeat_at = time.monotonic()
        try:
            status = VoiceStatus(
                state=self.runtime.state,
                enabled=self.runtime.state != VoiceState.DISABLED,
                session_id=self.runtime.session_id,
                turn_id=self.runtime.turn_id,
                last_error=self.runtime.last_error,
                component_latency_ms={
                    "asr": getattr(self, "_latency_asr", None),
                    "assistant": getattr(self, "_latency_assistant", None),
                    "tts": getattr(self, "_latency_tts", None),
                },
            )
            await self.gateway.heartbeat(status)
        except Exception:
            logger.debug("voice heartbeat unavailable", exc_info=True)

    def _fail(self, state: VoiceState, code: str, exc: Exception | None) -> None:
        message = str(exc) if exc else code
        # Only categories are sent to logs/status; adapter exception text may contain secrets.
        logger.warning("voice component failure code=%s", code)
        self._set_state(state, {"code": code, "message": code, "recoverable": True})

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
        if self.runtime.state == VoiceState.SPEAKING:
            self._set_state(VoiceState.CAPTURING)
            self._followup_until = time.monotonic() + getattr(self.config, "followup_seconds", 8.0)
