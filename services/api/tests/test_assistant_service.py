from __future__ import annotations

import pytest

from app.models.assistant import AssistantDecision, MappingAction, VoiceAssistantRequest
from app.models.mapping import MappingState, MappingStatus, MappingCommandResult
from app.services.assistant_service import AssistantService


class FakeProvider:
    def __init__(self, decision: AssistantDecision):
        self.decision = decision
        self.calls = 0

    async def decide(self, transcript, context, history):
        self.calls += 1
        return self.decision

    async def close(self):
        pass


class RecordingBackend:
    def __init__(self, state=MappingState.IDLE):
        self.status_value = MappingStatus(state=state, ready=state is MappingState.MAPPING,
                                          motion_allowed=state is MappingState.MAPPING)
        self.calls = []

    async def status(self):
        return self.status_value.model_copy(deep=True)

    async def start(self, session_id):
        self.calls.append(("start", session_id))
        return MappingCommandResult(accepted=True, state=MappingState.STARTING, message="accepted")

    async def pause(self):
        self.calls.append(("pause",))
        return MappingCommandResult(accepted=True, state=MappingState.PAUSED, message="accepted")

    async def resume(self):
        self.calls.append(("resume",))
        return MappingCommandResult(accepted=True, state=MappingState.MAPPING, message="accepted")

    async def stop(self):
        self.calls.append(("stop",))
        return MappingCommandResult(accepted=True, state=MappingState.IDLE, message="accepted")

    async def save(self, map_name):
        self.calls.append(("save", map_name))
        return MappingCommandResult(accepted=True, state=MappingState.MAPPING, message="accepted")

    async def load(self, request):
        raise AssertionError("voice must not load maps")

    async def close(self):
        pass


def req(text, session="s1", turn="t1"):
    return VoiceAssistantRequest(session_id=session, turn_id=turn, transcript=text)


@pytest.mark.anyio
async def test_action_is_pending_until_same_session_confirmation():
    provider = FakeProvider(AssistantDecision(reply_text="确认开始？", action=MappingAction(type="mapping_start")))
    backend = RecordingBackend()
    service = AssistantService(provider, backend, confirmation_ttl_seconds=15)

    first = await service.handle(req("开始建图"))
    assert first.state == "awaiting_confirmation"
    assert backend.calls == []

    other = await service.handle(req("确认", session="other", turn="t2"))
    assert other.state == "awaiting_confirmation"
    assert backend.calls == []

    done = await service.handle(req("确认", turn="t3"))
    assert done.state == "executed"
    assert backend.calls == [("start", "s1")]


@pytest.mark.anyio
async def test_cancel_clears_pending_without_backend_call():
    provider = FakeProvider(AssistantDecision(reply_text="是否暂停？", action=MappingAction(type="mapping_pause")))
    backend = RecordingBackend(MappingState.MAPPING)
    service = AssistantService(provider, backend)
    assert (await service.handle(req("暂停"))).state == "awaiting_confirmation"
    response = await service.handle(req("取消", turn="t2"))
    assert response.state == "rejected"
    assert backend.calls == []


@pytest.mark.anyio
async def test_status_query_does_not_create_action():
    provider = FakeProvider(AssistantDecision(reply_text="当前空闲。", action=None))
    backend = RecordingBackend()
    service = AssistantService(provider, backend)
    response = await service.handle(req("当前状态？"))
    assert response.state == "completed"
    assert response.action is None
    assert backend.calls == []
