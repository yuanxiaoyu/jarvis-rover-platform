import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings
from app.models.garbage import GarbageDetection, GarbageReport, GarbageReportStatus


def build_openclaw_payload(detection: GarbageDetection) -> dict[str, object]:
    return {
        "event_type": "garbage_detection",
        "source": "jarvis_rover",
        "target": settings.openclaw_report_target,
        "task_id": detection.task_id,
        "detection_id": detection.detection_id,
        "room_label": detection.room_label,
        "summary": detection.summary,
        "confidence": detection.confidence,
        "image_url": detection.image_url,
        "created_at": detection.created_at.isoformat(),
    }


def send_detection_report(detection: GarbageDetection) -> GarbageReport:
    if not settings.openclaw_enabled:
        return GarbageReport(
            status=GarbageReportStatus.SKIPPED,
            message="OpenClaw reporting disabled by configuration.",
        )

    if not settings.openclaw_webhook_url:
        return GarbageReport(
            status=GarbageReportStatus.NOT_CONFIGURED,
            message="ROVER_OPENCLAW_WEBHOOK_URL 未配置，未向飞书发送图片。",
        )

    payload = json.dumps(build_openclaw_payload(detection)).encode("utf-8")
    request = Request(
        settings.openclaw_webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=settings.openclaw_timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="ignore")
            if 200 <= response.status < 300:
                return GarbageReport(
                    status=GarbageReportStatus.SENT,
                    message=response_body or "OpenClaw accepted garbage detection event.",
                    delivered_at=datetime.now(timezone.utc),
                )
            return GarbageReport(
                status=GarbageReportStatus.FAILED,
                message=f"OpenClaw returned HTTP {response.status}: {response_body}",
            )
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return GarbageReport(
            status=GarbageReportStatus.FAILED,
            message=f"OpenClaw HTTPError {exc.code}: {body}",
        )
    except URLError as exc:
        return GarbageReport(
            status=GarbageReportStatus.FAILED,
            message=f"OpenClaw URLError: {exc.reason}",
        )
