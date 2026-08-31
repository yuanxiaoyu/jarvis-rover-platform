from rover_voice.contracts import VoiceState
from rover_voice.state_machine import StateMachine


def test_explicit_wake_capture_transition():
    machine = StateMachine()
    machine.transition(VoiceState.WAKE_LISTENING)
    machine.transition(VoiceState.CAPTURING)
    assert machine.runtime.state is VoiceState.CAPTURING
