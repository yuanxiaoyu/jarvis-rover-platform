import asyncio

import pytest

from app.models.mapping import MappingState
from app.services.ros_bridge import RosMappingBridge, RosStatusSnapshot, _api_state


def test_unknown_ros_state_is_safe_error_state():
    assert _api_state(99) is MappingState.ERROR_RECOVERABLE


def test_status_snapshot_defaults_to_locked():
    snapshot = RosStatusSnapshot(
        state=0,
        session_id="",
        ready=False,
        motion_allowed=False,
        map_update_age_s=None,
        current_revision=None,
        last_error="",
        received_at=None,
    )
    assert snapshot.motion_allowed is False


def test_bridge_rejects_command_before_start():
    bridge = RosMappingBridge(service_timeout_seconds=0.01)

    async def exercise():
        with pytest.raises(RuntimeError, match="not started"):
            await bridge.command(0, session_id="room-1")

    asyncio.run(exercise())
