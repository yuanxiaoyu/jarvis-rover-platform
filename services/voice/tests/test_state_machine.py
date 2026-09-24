from rover_voice.contracts import VoiceState
from rover_voice.state_machine import StateMachine


def test_explicit_wake_capture_transition():
    machine = StateMachine()
    machine.transition(VoiceState.WAKE_LISTENING)
    machine.transition(VoiceState.CAPTURING)
    assert machine.runtime.state is VoiceState.CAPTURING


def test_illegal_transition_is_rejected():
    machine = StateMachine()
    try:
        machine.transition(VoiceState.SPEAKING)
    except ValueError as exc:
        assert "invalid voice transition" in str(exc)
    else:
        raise AssertionError("disabled must not transition directly to speaking")


def test_queued_tts_can_interrupt_wake_listening():
    machine = StateMachine()
    machine.transition(VoiceState.WAKE_LISTENING)
    machine.transition(VoiceState.SPEAKING)
    assert machine.runtime.state is VoiceState.SPEAKING
