from __future__ import annotations

import pytest

from app.models.assistant import AssistantDecision, MappingAction, VoiceAssistantRequest
from app.models.mapping import MappingCommandResult, MappingState, MappingStatus
from app.services.assistant_service import AssistantService


class FakeProvider:
    async def decide(self, transcript, context, history):
        return AssistantDecision(reply_text="可以开始建图，请确认。", action=MappingAction(type="mapping_start"), confidence=1)

    async def close(self):
        return None


class FakeMapping:
    def __init__(self):
        self.state = MappingState.IDLE
        self.calls = []

    async def status(self):
        return MappingStatus(state=self.state, ready=self.state is MappingState.MAPPING,
                             motion_allowed=self.state is MappingState.MAPPING)

    async def start(self, session_id):
        self.calls.append("start")
        self.state = MappingState.STARTING
        return MappingCommandResult(accepted=True, state=self.state, message="start accepted")

    async def pause(self): raise AssertionError("unexpected pause")
    async def resume(self): raise AssertionError("unexpected resume")
    async def stop(self): raise AssertionError("unexpected stop")
    async def save(self, map_name): raise AssertionError("unexpected save")
    async def load(self, request): raise AssertionError("unexpected load")
    async def close(self): return None


@pytest.mark.anyio
async def test_fake_voice_to_mapping_requires_two_turns_and_never_touches_motion():
    mapping = FakeMapping()
    service = AssistantService(FakeProvider(), mapping)
    first = await service.handle(VoiceAssistantRequest(session_id="voice", turn_id="one", transcript="开始建图"))
    assert first.state == "awaiting_confirmation"
    assert mapping.calls == []
    second = await service.handle(VoiceAssistantRequest(session_id="voice", turn_id="two", transcript="确认"))
    assert second.state == "executed"
    assert mapping.calls == ["start"]
    assert not hasattr(mapping, "cmd_vel")
