from __future__ import annotations
import asyncio
import uuid
from collections import deque
from .contracts import VoiceRuntime, VoiceState
from .state_machine import StateMachine


class VoiceService:
    def __init__(self, config, audio_input, wakeword, asr, tts, gateway):
        self.config, self.audio_input, self.wakeword, self.asr, self.tts, self.gateway = config, audio_input, wakeword, asr, tts, gateway
        self.machine = StateMachine()
        self.runtime = self.machine.runtime
        self.frames = deque(maxlen=750)
        self.running = False

    def enable(self):
        self.machine.transition(VoiceState.WAKE_LISTENING)
        self.runtime.session_id = None

    def transition(self, next_state):
        self.machine.transition(next_state)

    def process_frame(self, frame: bytes) -> None:
        if self.runtime.state == VoiceState.WAKE_LISTENING and self.wakeword.process(frame):
            self.runtime.session_id, self.runtime.turn_id = uuid.uuid4().hex, None
            self.frames.clear(); self.machine.transition(VoiceState.CAPTURING); return
        if self.runtime.state == VoiceState.CAPTURING:
            self.frames.append(frame)
            if not self.asr.is_speech(frame) and self.frames:
                self.machine.transition(VoiceState.PROCESSING_ASR)

    def run_pending_once(self) -> None:
        if self.runtime.state == VoiceState.PROCESSING_ASR:
            self.machine.transition(VoiceState.PROCESSING_ASSISTANT)
        elif self.runtime.state == VoiceState.PROCESSING_ASSISTANT:
            self.machine.transition(VoiceState.SPEAKING)

    async def run(self) -> None:
        self.running = True
        self.enable()
        async for frame in self.audio_input.start():
            if not self.running: break
            self.process_frame(frame)

    def stop(self) -> None:
        self.running = False
