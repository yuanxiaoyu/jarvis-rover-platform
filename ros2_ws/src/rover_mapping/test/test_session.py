from rover_mapping.session import CommandType, MappingState, SessionController


def test_new_controller_is_idle_and_motion_locked() -> None:
    controller = SessionController("room-20260828")

    snapshot = controller.snapshot()

    assert snapshot.session_id == "room-20260828"
    assert snapshot.state is MappingState.IDLE
    assert snapshot.motion_allowed is False


def test_start_requires_successful_preflight() -> None:
    controller = SessionController("room-20260828")

    result = controller.request(CommandType.START, preflight_ok=False)

    assert result.accepted is False
    assert "preflight" in result.message.lower()
    assert controller.snapshot().state is MappingState.IDLE


def test_start_pause_resume_stop_lifecycle() -> None:
    controller = SessionController("room-20260828")

    assert controller.request(CommandType.START, preflight_ok=True).accepted is True
    assert controller.snapshot().state is MappingState.STARTING

    controller.mark_started()
    snapshot = controller.snapshot()
    assert snapshot.state is MappingState.MAPPING
    assert snapshot.motion_allowed is True

    assert controller.request(CommandType.PAUSE).accepted is True
    controller.mark_paused()
    snapshot = controller.snapshot()
    assert snapshot.state is MappingState.PAUSED
    assert snapshot.motion_allowed is False

    assert controller.request(CommandType.RESUME, preflight_ok=True).accepted is True
    controller.mark_resumed()
    assert controller.snapshot().state is MappingState.MAPPING

    assert controller.request(CommandType.STOP).accepted is True
    assert controller.snapshot().state is MappingState.SAVING

    controller.mark_saved()
    assert controller.snapshot().state is MappingState.IDLE


def test_resume_from_idle_is_rejected_without_mutation() -> None:
    controller = SessionController("room-20260828")

    result = controller.request(CommandType.RESUME, preflight_ok=True)

    assert result.accepted is False
    assert controller.snapshot().state is MappingState.IDLE


def test_mark_failed_enters_recoverable_error_and_preserves_message() -> None:
    controller = SessionController("room-20260828")

    controller.mark_failed("slam service unavailable")

    snapshot = controller.snapshot()
    assert snapshot.state is MappingState.ERROR_RECOVERABLE
    assert snapshot.motion_allowed is False
    assert snapshot.last_error == "slam service unavailable"


def test_start_can_recover_after_error_when_preflight_passes() -> None:
    controller = SessionController("room-20260828")
    controller.mark_failed("temporary sensor outage")

    result = controller.request(CommandType.START, preflight_ok=True)

    assert result.accepted is True
    assert controller.snapshot().state is MappingState.STARTING
    assert controller.snapshot().last_error == ""
