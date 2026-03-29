from datetime import datetime, timezone
from uuid import uuid4

from app.models.mission import MissionMode
from app.models.task import Task, TaskStatus, TaskType
from app.state import MISSION_STATE, TASK_STATE

WHOLE_HOME_KEYWORDS = ("整屋", "全屋", "整个房屋", "整个家", "whole house", "entire house", "entire home")
GARBAGE_KEYWORDS = ("垃圾", "废弃物", "trash", "garbage", "waste")
PHOTO_KEYWORDS = ("拍照", "拍张照", "照片", "image", "photo", "picture")
REPORT_KEYWORDS = ("告诉我", "通知我", "上报", "汇报", "飞书", "feishu", "openclaw")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def infer_command_intent(text: str, fallback_intent: str = "unknown") -> str:
    normalized = text.lower().strip()
    if looks_like_whole_home_garbage_scan(normalized):
        return "whole_home_garbage_scan"
    return fallback_intent.lower().strip() or "unknown"


def looks_like_whole_home_garbage_scan(text: str) -> bool:
    return (
        _contains_any(text, WHOLE_HOME_KEYWORDS)
        and _contains_any(text, GARBAGE_KEYWORDS)
        and _contains_any(text, PHOTO_KEYWORDS)
        and _contains_any(text, REPORT_KEYWORDS)
    )


def queue_whole_home_garbage_scan(source_text: str, source: str) -> Task:
    now = datetime.now(timezone.utc)
    task = Task(
        task_id=f"task-{uuid4().hex[:8]}",
        type=TaskType.WHOLE_HOME_SCAN,
        status=TaskStatus.RUNNING,
        description="整屋扫描并识别垃圾，发现后拍照并通过 OpenClaw 上报飞书。",
        metadata={
            "source": source,
            "source_text": source_text,
            "report_channel": "openclaw",
            "report_target": "feishu",
            "requires_photo": True,
            "scope": "whole_home",
            "object_detection_label": "garbage",
        },
        created_at=now,
        updated_at=now,
    )
    TASK_STATE.insert(0, task)
    MISSION_STATE.mode = MissionMode.AUTONOMY
    MISSION_STATE.objective = "整屋扫描并识别垃圾"
    MISSION_STATE.status_line = "整屋扫描任务已启动，发现垃圾后将拍照并通过 OpenClaw 上报飞书"
    return task
