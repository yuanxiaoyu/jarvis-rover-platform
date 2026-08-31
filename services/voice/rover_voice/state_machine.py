from __future__ import annotations
from dataclasses import dataclass
from .contracts import VoiceRuntime, VoiceState


_ALLOWED = {
    VoiceState.DISABLED: {VoiceState.WAKE_LISTENING},
    VoiceState.WAKE_LISTENING: {VoiceState.CAPTURING, VoiceState.AUDIO_UNAVAILABLE, VoiceState.DISABLED},
    VoiceState.CAPTURING: {VoiceState.PROCESSING_ASR, VoiceState.WAKE_LISTENING, VoiceState.DISABLED},
    VoiceState.PROCESSING_ASR: {VoiceState.PROCESSING_ASSISTANT, VoiceState.ASR_ERROR},
    VoiceState.PROCESSING_ASSISTANT: {VoiceState.SPEAKING, VoiceState.ASSISTANT_UNAVAILABLE},
    VoiceState.SPEAKING: {VoiceState.CAPTURING, VoiceState.WAKE_LISTENING, VoiceState.TTS_ERROR},
    VoiceState.AUDIO_UNAVAILABLE: {VoiceState.WAKE_LISTENING, VoiceState.DISABLED},
    VoiceState.ASR_ERROR: {VoiceState.CAPTURING, VoiceState.WAKE_LISTENING},
    VoiceState.ASSISTANT_UNAVAILABLE: {VoiceState.WAKE_LISTENING, VoiceState.CAPTURING},
    VoiceState.TTS_ERROR: {VoiceState.WAKE_LISTENING, VoiceState.CAPTURING},
}


class StateMachine:
    def __init__(self):
        self.runtime = VoiceRuntime()

    def transition(self, next_state: VoiceState) -> None:
        if next_state != self.runtime.state and next_state not in _ALLOWED.get(self.runtime.state, set()):
            raise ValueError(f"invalid voice transition {self.runtime.state}->{next_state}")
        self.runtime.state = next_state
