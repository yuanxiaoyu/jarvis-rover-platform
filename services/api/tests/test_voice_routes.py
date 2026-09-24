from contextlib import contextmanager
from typing import Iterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.main import app
from app.models.assistant import VoiceAssistantResponse, VoiceStatus


class FakeAssistant:
    async def handle(self, request):
        return VoiceAssistantResponse(
            session_id=request.session_id,
            turn_id=request.turn_id,
            state="completed",
            reply_text="当前状态正常。",
        )


@contextmanager
def client_with_voice(*, token: str | None = "gateway-test-token") -> Iterator[TestClient]:
    old_token = settings.voice_gateway_token
    old_service = getattr(app.state, "assistant_service", None)
    old_store = getattr(app.state, "voice_status_store", None)
    app.state.assistant_service = FakeAssistant()
    settings.voice_gateway_token = SecretStr(token) if token is not None else None
    try:
        with TestClient(app, client=("127.0.0.1", 8001)) as client:
            yield client
    finally:
        settings.voice_gateway_token = old_token
        if old_service is None:
            if hasattr(app.state, "assistant_service"):
                del app.state.assistant_service
        else:
            app.state.assistant_service = old_service
        if old_store is None:
            if hasattr(app.state, "voice_status_store"):
                del app.state.voice_status_store
        else:
            app.state.voice_status_store = old_store


def request_json() -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": "voice-1",
        "turn_id": "turn-1",
        "transcript": "当前状态",
        "language": "zh-CN",
        "confidence": 0.9,
        "source": "local-sherpa-onnx",
    }


def test_voice_assistant_requires_token():
    with client_with_voice() as client:
        response = client.post("/api/v1/voice/assistant", json=request_json())
    assert response.status_code == 401


def test_voice_assistant_returns_service_response_with_token():
    with client_with_voice() as client:
        response = client.post(
            "/api/v1/voice/assistant",
            headers={"X-Rover-Voice-Token": "gateway-test-token"},
            json=request_json(),
        )
    assert response.status_code == 200
    assert response.json()["schema_version"] == 1
    assert response.json()["action"] is None


def test_voice_assistant_rejects_client_action_and_unknown_source():
    with client_with_voice() as client:
        headers = {"X-Rover-Voice-Token": "gateway-test-token"}
        action = {**request_json(), "action": {"type": "mapping_start"}}
        source = {**request_json(), "source": "browser"}
        assert client.post("/api/v1/voice/assistant", headers=headers, json=action).status_code == 422
        assert client.post("/api/v1/voice/assistant", headers=headers, json=source).status_code == 422


def test_status_is_unavailable_before_heartbeat_and_fresh_after_heartbeat():
    with client_with_voice() as client:
        stale = client.get("/api/v1/voice/status")
        assert stale.status_code == 200
        assert stale.json()["enabled"] is False
        assert stale.json()["last_error"]["code"] == "assistant_unavailable"

        status = VoiceStatus(state="wake_listening", enabled=True, session_id="voice-1")
        fresh = client.post(
            "/api/v1/voice/heartbeat",
            headers={"X-Rover-Voice-Token": "gateway-test-token"},
            json=status.model_dump(mode="json"),
        )
        assert fresh.status_code == 200
        assert client.get("/api/v1/voice/status").json()["state"] == "wake_listening"


def test_component_error_heartbeat_is_accepted_and_visible():
    with client_with_voice() as client:
        headers = {"X-Rover-Voice-Token": "gateway-test-token"}
        status = VoiceStatus(
            state="tts_error",
            enabled=True,
            last_error={"code": "tts_error", "message": "tts_error", "recoverable": True},
        )
        response = client.post(
            "/api/v1/voice/heartbeat",
            headers=headers,
            json=status.model_dump(mode="json"),
        )
        assert response.status_code == 200
        assert client.get("/api/v1/voice/status").json()["last_error"]["code"] == "tts_error"


def test_legacy_voice_routes_are_removed():
    with client_with_voice() as client:
        assert client.post("/api/v1/voice/session").status_code == 410
        assert client.post("/api/v1/voice/command").status_code == 410
