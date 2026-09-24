import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.mapping import MappingCommandResult, MappingState, SessionRequest
from app.models.mission import MissionState
from app.routers.missions import exploration_status, start_exploration


class FakeZoneStore:
    def __init__(self, zones):
        self.zones = zones

    def list(self):
        return self.zones


class FakeRuntime:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.started = None

    def start_exploration(self, session_id, zones):
        self.started = (session_id, zones)
        return MappingCommandResult(
            accepted=self.accepted,
            state=MappingState.STARTING,
            message="exploration queued" if self.accepted else "safety gate is unavailable",
        )

    def mission_state(self):
        return MissionState(
            mode="autonomy",
            exploration_state="exploring",
            exploration_message="Navigating to frontier",
            completed_frontiers=2,
            failed_frontiers=1,
        )


def make_request(runtime, zones):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ros_runtime=runtime, zone_store=FakeZoneStore(zones))))


def test_exploration_start_passes_session_and_zone_snapshot_to_runtime():
    runtime = FakeRuntime()
    zones = [object()]
    request = make_request(runtime, zones)

    response = asyncio.run(start_exploration(request, SessionRequest(session_id="web-session")))

    assert response.accepted is True
    assert runtime.started == ("web-session", zones)


def test_exploration_start_reports_runtime_preflight_rejection():
    runtime = FakeRuntime(accepted=False)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(start_exploration(make_request(runtime, []), SessionRequest(session_id="web-session")))

    assert raised.value.status_code == 409
    assert "safety gate" in raised.value.detail


def test_exploration_status_returns_runtime_progress():
    runtime = FakeRuntime()

    status = exploration_status(make_request(runtime, []))

    assert status.exploration_state == "exploring"
    assert status.completed_frontiers == 2
    assert status.failed_frontiers == 1
