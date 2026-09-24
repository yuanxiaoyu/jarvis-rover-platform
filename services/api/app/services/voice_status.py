from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

from app.models.assistant import AssistantError, VoiceStatus


class VoiceStatusStore:
    """Keep the latest host voice status and a bounded local TTS queue."""

    def __init__(self, stale_seconds: float = 15.0) -> None:
        if stale_seconds <= 0:
            raise ValueError("stale_seconds must be positive")
        self._stale_seconds = stale_seconds
        self._status: VoiceStatus | None = None
        self._updated_at: float | None = None
        self._tts_queue: deque[str] = deque(maxlen=1)

    def update(self, status: VoiceStatus) -> None:
        self._status = status.model_copy(deep=True)
        self._updated_at = time.monotonic()

    def current(self) -> VoiceStatus:
        if self._status is None or self._updated_at is None:
            return self._unavailable()
        if time.monotonic() - self._updated_at > self._stale_seconds:
            return self._unavailable()
        return self._status.model_copy(deep=True)

    def enqueue_tts(self, text: str) -> bool:
        if not text or not text.strip() or len(text) > 2000:
            raise ValueError("TTS text must contain 1 to 2000 characters")
        if self._tts_queue:
            return False
        self._tts_queue.append(text)
        return True

    def pop_tts(self) -> str | None:
        return self._tts_queue.popleft() if self._tts_queue else None

    @staticmethod
    def _unavailable() -> VoiceStatus:
        return VoiceStatus(
            state="disabled",
            enabled=False,
            last_error=AssistantError(
                code="assistant_unavailable",
                message="语音服务状态不可用",
                recoverable=True,
            ),
            received_at=datetime.now(timezone.utc),
        )
