from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.models.garbage import GarbageDetection, GarbageDetectionCreate, GarbageReport
from app.models.task import TaskStatus, TaskType
from app.services.garbage_reporting import send_detection_report
from app.state import GARBAGE_DETECTION_STATE, MISSION_STATE, TASK_STATE

router = APIRouter(prefix="/garbage", tags=["garbage"])


@router.get("/detections", response_model=list[GarbageDetection])
def list_garbage_detections() -> list[GarbageDetection]:
    return GARBAGE_DETECTION_STATE


@router.post("/detections", response_model=GarbageDetection)
def create_garbage_detection(payload: GarbageDetectionCreate) -> GarbageDetection:
    task = None
    if payload.task_id:
        task = next((item for item in TASK_STATE if item.task_id == payload.task_id), None)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

    detection = GarbageDetection(
        detection_id=f"garbage-{uuid4().hex[:8]}",
        task_id=payload.task_id,
        room_label=payload.room_label,
        image_url=payload.image_url,
        summary=payload.summary,
        confidence=payload.confidence,
        source=payload.source,
        created_at=datetime.now(timezone.utc),
    )

    if payload.auto_report:
        detection.report = send_detection_report(detection)
    else:
        detection.report = GarbageReport(message="自动上报已关闭。")

    if task is not None and task.type == TaskType.WHOLE_HOME_SCAN:
        task.status = TaskStatus.RUNNING
        task.updated_at = datetime.now(timezone.utc)

    GARBAGE_DETECTION_STATE.insert(0, detection)
    MISSION_STATE.status_line = (
        f"在{payload.room_label}发现疑似垃圾，"
        f"上报状态：{detection.report.status.value}"
    )
    return detection
