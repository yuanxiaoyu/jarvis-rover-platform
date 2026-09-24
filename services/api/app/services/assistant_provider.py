from __future__ import annotations

import json
import logging
import time
from typing import Protocol
from uuid import uuid4

import httpx
from pydantic import SecretStr, ValidationError

from app.models.assistant import AssistantDecision

logger = logging.getLogger(__name__)

_FORBIDDEN_DECISION_TEXT = (
    "cmd_vel", "ros2", "ros service", "ros topic", "shell", "sudo",
    "线速度", "角速度", "移动小车", "路径执行", "云台", "http://", "https://",
)


def _validate_decision_safety(decision: AssistantDecision) -> None:
    """Reject model output that attempts to cross the local capability boundary."""
    text = decision.reply_text.casefold()
    if any(token in text for token in _FORBIDDEN_DECISION_TEXT):
        raise ValueError("assistant response contains a forbidden control field")
    if decision.action is not None and decision.action.type not in {
        "mapping_start", "mapping_pause", "mapping_resume", "mapping_save", "mapping_stop",
    }:
        raise ValueError("assistant action is not allowlisted")


class AssistantProviderError(RuntimeError):
    def __init__(self, code: str, message: str, recoverable: bool = True) -> None:
        self.code, self.message, self.recoverable = code, message, recoverable
        super().__init__(message)


class AssistantProvider(Protocol):
    async def decide(self, transcript: str, context: dict[str, object], history: list[dict[str, str]]) -> AssistantDecision: ...

    async def close(self) -> None: ...


class OpenAICompatibleAssistantProvider:
    def __init__(self, base_url: str, api_key: SecretStr, model: str = "gpt-5.6", timeout_seconds: float = 20.0, max_output_tokens: int = 512, transport: httpx.AsyncClient | None = None, wire_api: str = "chat_completions") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.wire_api = wire_api
        self._client = transport or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=5.0))
        self._owns_client = transport is None

    @property
    def endpoint(self) -> str:
        suffix = "/responses" if self.wire_api == "responses" else "/chat/completions"
        return self.base_url if self.base_url.endswith(suffix) else f"{self.base_url}{suffix}"

    @staticmethod
    def _needs_substantive_reply(transcript: str) -> bool:
        return any(token in transcript for token in ("笑话", "脑筋急转弯", "谜语", "知识", "答案"))

    async def decide(self, transcript: str, context: dict[str, object], history: list[dict[str, str]]) -> AssistantDecision:
        system = "你是贾维斯，一个友好、机智、会讲趣味内容的机器人助手。你可以自然地进行闲聊、知识问答、讲笑话、脑筋急转弯和创意对话，不要把回答限制为小车控制。用户要求笑话、脑筋急转弯或知识答案时，必须直接给出实际内容，不能只回复‘好的’或‘收到’。只能返回 JSON，action 只能是 mapping_start、mapping_pause、mapping_resume、mapping_save、mapping_stop 或 null；普通对话必须使用 action=null。禁止移动、路径、云台、ROS、shell、/cmd_vel。建图动作必须由本地服务二次确认。"
        messages = [{"role": "system", "content": system}, *history[-8:], {"role": "user", "content": json.dumps({"transcript": transcript, "context": context}, ensure_ascii=False)}]
        if self.wire_api == "responses":
            payload = {"model": self.model, "input": messages, "max_output_tokens": self.max_output_tokens, "temperature": 0}
        else:
            payload = {"model": self.model, "messages": messages, "max_tokens": self.max_output_tokens, "temperature": 0}
        request_id = uuid4().hex[:12]
        for attempt in range(2):
            request_payload = payload
            if attempt == 1 and self._needs_substantive_reply(transcript):
                reminder = {
                    "role": "system",
                    "content": "上一轮没有满足用户要求。请现在直接给出完整的笑话、谜语或知识答案，不要只回复确认词；仍然只返回约定 JSON。",
                }
                retry_messages = [*messages, reminder]
                if self.wire_api == "responses":
                    request_payload = {**payload, "input": retry_messages}
                else:
                    request_payload = {**payload, "messages": retry_messages}
            started = time.monotonic()
            try:
                response = await self._client.post(self.endpoint, json=request_payload, headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}", "X-Request-ID": request_id})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == 0:
                    continue
                raise AssistantProviderError("assistant_unavailable", "助手服务暂时不可用", True) from exc
            elapsed = int((time.monotonic() - started) * 1000)
            logger.info("assistant provider request=%s status=%s elapsed_ms=%s", request_id, response.status_code // 100, elapsed)
            if response.status_code in (429,) or response.status_code >= 500:
                if attempt == 0:
                    continue
                raise AssistantProviderError("assistant_unavailable", "助手服务暂时不可用", True)
            if response.status_code == 401:
                raise AssistantProviderError("assistant_unavailable", "助手认证失败（401）", False)
            if response.status_code >= 400:
                raise AssistantProviderError("assistant_unavailable", f"助手请求失败（{response.status_code}）", True)
            content: object = None
            try:
                body = response.json()
                if self.wire_api == "responses":
                    content = body.get("output_text")
                    if not content:
                        for output in body.get("output", []):
                            if not isinstance(output, dict):
                                continue
                            items = [output] if output.get("text") or output.get("output_text") else output.get("content", [])
                            if isinstance(items, dict):
                                items = [items]
                            for item in items:
                                if isinstance(item, dict) and item.get("type", "output_text") == "output_text":
                                    content = item.get("text") or item.get("output_text")
                                    if content:
                                        break
                            if content:
                                break
                    if not content and body.get("status") == "completed":
                        content = "好的。"
                else:
                    content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                try:
                    decision = AssistantDecision.model_validate_json(content)
                except ValidationError:
                    try:
                        parsed = json.loads(content)
                    except json.JSONDecodeError:
                        if content.startswith(("{", "[")):
                            raise
                        decision = AssistantDecision(reply_text=content, action=None, confidence=None)
                    else:
                        if isinstance(parsed, dict):
                            # Providers commonly call the natural-language field
                            # `message`, `answer`, `response`, `content`, or `text`; normalize
                            # those aliases while retaining structured actions.
                            reply = next(
                                (parsed.get(key) for key in ("reply_text", "message", "answer", "response", "content", "text")
                                 if isinstance(parsed.get(key), str) and parsed.get(key).strip()),
                                "好的。",
                            )
                            normalized = {key: parsed[key] for key in ("action", "confidence") if key in parsed}
                            normalized["reply_text"] = reply
                            decision = AssistantDecision.model_validate(normalized)
                        else:
                            raise
                _validate_decision_safety(decision)
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
                logger.warning("assistant provider invalid response type=%s", type(exc).__name__)
                # A slow upstream occasionally returns a truncated JSON body.
                # Retry that transport-level framing error once, but never
                # retry safety-policy or schema validation failures.
                if attempt == 0 and isinstance(exc, json.JSONDecodeError):
                    continue
                raise AssistantProviderError("invalid_decision", "助手返回格式无效", False) from exc
            if attempt == 0 and self._needs_substantive_reply(transcript) and decision.reply_text.strip() in {"好的", "好的。", "收到", "收到。", "没问题", "没问题。"}:
                continue
            return decision
        raise AssistantProviderError("assistant_unavailable", "助手服务暂时不可用", True)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
