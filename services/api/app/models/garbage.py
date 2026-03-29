from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class GarbageReportStatus(str, Enum):
    SKIPPED = "skipped"
    NOT_CONFIGURED = "not_configured"
    SENT = "sent"
    FAILED = "failed"


class GarbageReport(BaseModel):
    channel: str = "openclaw"
    target: str = "feishu"
    status: GarbageReportStatus = GarbageReportStatus.SKIPPED
    message: str = "未触发上报"
    delivered_at: datetime | None = None


class GarbageDetectionCreate(BaseModel):
    task_id: str | None = None
    room_label: str = Field(min_length=1)
    image_url: str = Field(min_length=1)
    summary: str = "发现疑似垃圾"
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    source: str = "vision_pipeline"
    auto_report: bool = True


class GarbageDetection(BaseModel):
    detection_id: str
    task_id: str | None = None
    room_label: str
    image_url: str
    summary: str
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    source: str = "vision_pipeline"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    report: GarbageReport = Field(default_factory=GarbageReport)
