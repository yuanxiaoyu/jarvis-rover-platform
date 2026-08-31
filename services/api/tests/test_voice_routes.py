from contextlib import contextmanager
from typing import Iterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.main import app
from app.models.assistant import AssistantDecision, VoiceAssistantResponse


class FakeAssistant:
    async def handle(self, request):
        return VoiceAssistantResponse(session_id=request.session_id, turn_id=request.turn_id,
                                      state="completed", reply_text="当前空闲。")


@contextmanager
def client_with_voice() -> Iterator[TestClient]:
    old_token = settings.voice_gateway_token
    app.state.assistant_service = FakeAssistant()
    settings.voice_gateway_token = SecretStr("gateway-test-token")
    try:
        with TestClient(app, client=("127.0.0.1", 8001)) as client:
            yield client
    finally:
        settings.voice_gateway_token = old_token
        app.state.assistant_service = None


def request_json():
    return {"schema_version": 1, "session_id": "voice-1", "turn_id": "turn-1",
            "transcript": "当前状态", "language": "zh-CN", "confidence": 0.9,
            "source": "local-sherpa-onnx"}


def test_voice_assistant_requires_token():
    with client_with_voice() as client:
        response = client.post("/api/v1/voice/assistant", json=request_json())
    assert response.status_code == 401


def test_voice_assistant_returns_service_response_with_token():
    with client_with_voice() as client:
        response = client.post("/api/v1/voice/assistant",
                               headers={"X-Rover-Voice-Token": "gateway-test-token"},
                               json=request_json())
    assert response.status_code == 200
    assert response.json()["schema_version"] == 1
    assert response.json()["action"] is None


def test_legacy_voice_routes_are_removed():
    with client_with_voice() as client:
        assert client.post("/api/v1/voice/session").status_code == 410
        assert client.post("/api/v1/voice/command").status_code == 410
