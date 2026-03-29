from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.routers.garbage as garbage_router
from app.main import app
from app.models.garbage import GarbageReport, GarbageReportStatus
from app.models.mission import MissionMode
from app.models.voice import VoiceSessionState
from app.state import GARBAGE_DETECTION_STATE, MISSION_STATE, TASK_STATE, VOICE_STATE

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    TASK_STATE.clear()
    GARBAGE_DETECTION_STATE.clear()
    MISSION_STATE.mode = MissionMode.IDLE
    MISSION_STATE.objective = "等待任务"
    MISSION_STATE.status_line = "待命"
    MISSION_STATE.selected_zone_id = None
    VOICE_STATE.listening = False
    VOICE_STATE.adapter = "mock"
    VOICE_STATE.transcript = "语音待命中"
    VOICE_STATE.wake_word = "贾维斯"
    yield


def test_voice_command_starts_whole_home_garbage_scan():
    response = client.post(
        "/api/v1/voice/command",
        json={
            "transcript": "贾维斯，请帮我扫描整个房屋，发现有垃圾请拍照告诉我",
            "intent": "unknown",
            "confidence": 0.97,
            "language": "zh-CN",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "whole_home_garbage_scan"
    assert payload["task_id"]
    assert TASK_STATE[0].type.value == "whole_home_scan"
    assert TASK_STATE[0].metadata["report_channel"] == "openclaw"
    assert MISSION_STATE.objective == "整屋扫描并识别垃圾"


def test_detection_endpoint_reports_via_openclaw(monkeypatch: pytest.MonkeyPatch):
    mission_response = client.post("/api/v1/missions/whole-home-garbage-scan", json={})
    assert mission_response.status_code == 200
    task_id = TASK_STATE[0].task_id

    def fake_send_detection_report(_detection):
        return GarbageReport(
            status=GarbageReportStatus.SENT,
            message="ok",
            delivered_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(garbage_router, "send_detection_report", fake_send_detection_report)

    response = client.post(
        "/api/v1/garbage/detections",
        json={
            "task_id": task_id,
            "room_label": "客厅",
            "image_url": "https://example.com/garbage.jpg",
            "summary": "沙发旁发现饮料瓶和纸屑",
            "confidence": 0.93,
            "source": "vision_pipeline",
            "auto_report": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["status"] == "sent"
    assert payload["room_label"] == "客厅"
    assert GARBAGE_DETECTION_STATE[0].task_id == task_id
