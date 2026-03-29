from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter

from app.models.task import Task, TaskStatus, TaskType
from app.models.voice import VoiceAck, VoiceCommand, VoiceSessionState
from app.services.command_orchestrator import infer_command_intent, queue_whole_home_garbage_scan
from app.state import TASK_STATE, VOICE_STATE

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/session", response_model=VoiceSessionState)
def set_voice_session(action: dict[str, str]) -> VoiceSessionState:
    next_action = action.get("action", "stop")
    VOICE_STATE.listening = next_action == "start"
    VOICE_STATE.transcript = "正在听取指令，请说“贾维斯”。" if VOICE_STATE.listening else "语音待命中"
    return VOICE_STATE


@router.post("/command", response_model=VoiceAck)
def process_voice_command(command: VoiceCommand) -> VoiceAck:
    normalized_intent = infer_command_intent(command.transcript, command.intent)
    adapter = "mock"

    if "sherpa" in command.transcript.lower():
        adapter = "sherpa-onnx"
        VOICE_STATE.adapter = adapter

    VOICE_STATE.transcript = command.transcript

    if normalized_intent == "whole_home_garbage_scan":
        task = queue_whole_home_garbage_scan(command.transcript, source="voice")
        return VoiceAck(
            accepted=True,
            message="Whole-home garbage scan started. Detections will be reported through OpenClaw.",
            intent=normalized_intent,
            adapter=adapter,
            task_id=task.task_id,
        )

    if normalized_intent in {"navigate", "go_to_point"}:
        now = datetime.now(timezone.utc)
        TASK_STATE.append(
            Task(
                task_id=f"task-{uuid4().hex[:8]}",
                type=TaskType.NAVIGATE,
                status=TaskStatus.PENDING,
                description=f"Created from voice transcript: {command.transcript}",
                created_at=now,
                updated_at=now,
            )
        )
        return VoiceAck(
            accepted=True,
            message="Navigation task queued.",
            intent=normalized_intent,
            adapter=adapter,
        )

    return VoiceAck(
        accepted=True,
        message="Command received.",
        intent=normalized_intent or "unknown",
        adapter=adapter,
    )
