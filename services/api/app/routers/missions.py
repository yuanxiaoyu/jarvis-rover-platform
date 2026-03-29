from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter

from app.models.map import Coordinate2D
from app.models.mission import AiCommandRequest, MissionMode, MissionState, NavigateRequest, WholeHomeGarbageScanRequest
from app.models.task import Task, TaskStatus, TaskType
from app.services.command_orchestrator import infer_command_intent, queue_whole_home_garbage_scan
from app.state import MISSION_STATE, TASK_STATE

router = APIRouter(prefix="/missions", tags=["missions"])


@router.post("/navigate", response_model=MissionState)
def navigate_to_zone(request: NavigateRequest) -> MissionState:
    MISSION_STATE.mode = MissionMode.AUTONOMY
    MISSION_STATE.selected_zone_id = request.zone_id
    MISSION_STATE.objective = f"导航至 {request.zone_id}"
    MISSION_STATE.status_line = "导航目标已下发"

    now = datetime.now(timezone.utc)
    TASK_STATE.append(
        Task(
            task_id=f"task-{uuid4().hex[:8]}",
            type=TaskType.NAVIGATE,
            status=TaskStatus.PENDING,
            target=Coordinate2D(x=0.0, y=0.0),
            description=f"Navigate to zone {request.zone_id}",
            created_at=now,
            updated_at=now,
        )
    )
    return MISSION_STATE


@router.post("/ai-command", response_model=MissionState)
def submit_ai_command(request: AiCommandRequest) -> MissionState:
    if infer_command_intent(request.prompt) == "whole_home_garbage_scan":
        queue_whole_home_garbage_scan(request.prompt, source="ai")
        return MISSION_STATE

    MISSION_STATE.mode = MissionMode.AUTONOMY
    MISSION_STATE.objective = request.prompt
    MISSION_STATE.status_line = "AI 指令已接收，等待任务编排"
    return MISSION_STATE


@router.post("/whole-home-garbage-scan", response_model=MissionState)
def start_whole_home_garbage_scan(request: WholeHomeGarbageScanRequest) -> MissionState:
    task = queue_whole_home_garbage_scan(request.transcript, source="api")
    task.metadata["report_channel"] = request.report_channel
    task.metadata["report_target"] = request.report_target
    task.metadata["requires_photo"] = request.require_photo
    task.updated_at = datetime.now(timezone.utc)
    MISSION_STATE.status_line = "整屋扫描任务已启动，发现垃圾后将拍照并通过 OpenClaw 上报飞书"
    return MISSION_STATE
