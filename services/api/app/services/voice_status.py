from __future__ import annotations

import time
from collections import deque

from app.models.assistant import AssistantError, VoiceStatus


class VoiceStatusStore:
    def __init__(self, stale_seconds: float = 15.0) -> None:
        self.stale_seconds = stale_seconds
        self._status = VoiceStatus(state="disabled", enabled=False)
        self._received_at: float | None = None
        self._tts_queue: deque[str] = deque(maxlen=1)

    def update(self, status: VoiceStatus) -> None:
        self._status = status
        self._received_at = time.monotonic()

    def current(self) -> VoiceStatus:
        if self._received_at is None or time.monotonic() - self._received_at > self.stale_seconds:
            return self._status.model_copy(update={"state": "assistant_unavailable", "enabled": False, "last_error": AssistantError(code="assistant_unavailable", message="voice heartbeat stale", recoverable=True)})
        return self._status.model_copy(deep=True)

    def enqueue_tts(self, text: str) -> None:
        self._tts_queue.clear()
        self._tts_queue.append(text)

    def pop_tts(self) -> str | None:
        return self._tts_queue.popleft() if self._tts_queue else None
