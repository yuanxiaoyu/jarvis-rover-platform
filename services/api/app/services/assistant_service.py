from __future__ import annotations

import time
from dataclasses import dataclass

from app.models.assistant import AssistantDecision, AssistantError, MappingAction, VoiceAssistantRequest, VoiceAssistantResponse
from app.models.mapping import MappingState, MappingStatus
from app.services.mapping_backend import MappingBackend
from app.services.assistant_provider import AssistantProvider, AssistantProviderError


@dataclass
class PendingConfirmation:
    session_id: str
    turn_id: str
    action: MappingAction
    expires_at: float


class AssistantService:
    def __init__(self, provider: AssistantProvider, mapping_backend: MappingBackend, confirmation_ttl_seconds: float = 15.0, transcript_max_chars: int = 1000) -> None:
        self._provider = provider
        self._mapping_backend = mapping_backend
        self._ttl = confirmation_ttl_seconds
        self._max_chars = transcript_max_chars
        self._pending: dict[str, PendingConfirmation] = {}
        self._history: dict[str, list[dict[str, str]]] = {}

    async def status_context(self) -> dict[str, object]:
        try:
            status = await self._mapping_backend.status()
            mapping = {"session_id": status.session_id, "state": status.state.value, "ready": status.ready, "motion_allowed": status.motion_allowed, "current_revision": status.current_revision, "last_error": status.last_error}
            reason = None
        except (RuntimeError, TimeoutError) as exc:
            mapping = {"state": "unavailable", "reason": "mapping status unavailable"}
            reason = str(exc)
        return {"mapping": mapping, "sources": {k: {"state": "unavailable", "reason": "voice context source not connected"} for k in ("map", "scan", "camera")}, "capabilities": {"mapping_actions": ["start", "pause", "resume", "save", "stop"], "motion": False, "path": False, "gimbal": False}, **({"error": "mapping unavailable"} if reason else {})}

    async def handle(self, request: VoiceAssistantRequest) -> VoiceAssistantResponse:
        if len(request.transcript) > self._max_chars:
            return self._response(request, "rejected", "语音内容过长。", error=("command_rejected", "语音内容过长", False))
        pending = self._pending.get(request.session_id)
        if pending:
            if pending.expires_at < time.monotonic():
                self._pending.pop(request.session_id, None)
            elif _is_cancel(request.transcript):
                self._pending.pop(request.session_id, None)
                return self._response(request, "rejected", "已取消操作。", action=pending.action)
            elif _is_confirm(request.transcript):
                try:
                    current = await self._mapping_backend.status()
                    self._validate_action(pending.action, current)
                    result = await self._execute(pending.action, request.session_id)
                except (RuntimeError, TimeoutError, ValueError) as exc:
                    self._pending.pop(request.session_id, None)
                    return self._response(request, "unavailable", "建图服务暂时不可用。", action=pending.action, error=("assistant_unavailable", "建图服务暂时不可用", True))
                self._pending.pop(request.session_id, None)
                if not result.accepted:
                    return self._response(request, "rejected", result.message or "操作未执行。", action=pending.action, error=("command_rejected", result.message or "操作未执行", False))
                return self._response(request, "executed", result.message or "操作已执行。", action=pending.action)
            else:
                return self._response(request, "awaiting_confirmation", "请明确说“确认”或“取消”。", action=pending.action)
        try:
            context = await self.status_context()
            decision = await self._provider.decide(request.transcript, context, self._history.get(request.session_id, []))
        except AssistantProviderError as exc:
            return self._response(request, "unavailable", "助手服务暂时不可用。", error=("assistant_unavailable", exc.message, exc.recoverable))
        self._history.setdefault(request.session_id, []).extend([{"role": "user", "content": request.transcript}, {"role": "assistant", "content": decision.reply_text}])
        if decision.action is None:
            return self._response(request, "completed", decision.reply_text)
        try:
            current = await self._mapping_backend.status()
            self._validate_action(decision.action, current)
        except (RuntimeError, TimeoutError):
            return self._response(request, "unavailable", "建图状态暂时不可用。", action=decision.action, error=("assistant_unavailable", "建图状态暂时不可用", True))
        except ValueError as exc:
            return self._response(request, "rejected", str(exc), action=decision.action, error=("command_rejected", str(exc), False))
        self._pending[request.session_id] = PendingConfirmation(request.session_id, request.turn_id, decision.action, time.monotonic() + self._ttl)
        return self._response(request, "awaiting_confirmation", decision.reply_text, action=decision.action)

    async def _execute(self, action: MappingAction, session_id: str):
        if action.type == "mapping_start":
            return await self._mapping_backend.start(session_id)
        if action.type == "mapping_pause":
            return await self._mapping_backend.pause()
        if action.type == "mapping_resume":
            return await self._mapping_backend.resume()
        if action.type == "mapping_save":
            return await self._mapping_backend.save(action.map_name or "map")
        return await self._mapping_backend.stop()

    @staticmethod
    def _validate_action(action: MappingAction, status: MappingStatus) -> None:
        valid = {"mapping_start": (MappingState.IDLE,), "mapping_pause": (MappingState.MAPPING,), "mapping_resume": (MappingState.PAUSED,), "mapping_save": (MappingState.MAPPING, MappingState.PAUSED), "mapping_stop": (MappingState.MAPPING, MappingState.PAUSED)}
        if status.state not in valid[action.type]:
            raise ValueError("当前建图状态不允许该操作")

    async def close(self) -> None:
        await self._provider.close()

    def _response(self, req, state, text, action=None, error=None):
        err = AssistantError(code=error[0], message=error[1], recoverable=error[2]) if error else None
        return VoiceAssistantResponse(session_id=req.session_id, turn_id=req.turn_id, state=state, reply_text=text, action=action, error=err)


def _is_confirm(text: str) -> bool:
    return text.strip() in {"确认", "是", "执行", "好的"}


def _is_cancel(text: str) -> bool:
    return text.strip() in {"取消", "否", "不要", "停止操作"}
