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

    async def decide(self, transcript: str, context: dict[str, object], history: list[dict[str, str]]) -> AssistantDecision:
        system = "你是贾维斯机器人助手。只能返回 JSON，action 只能是 mapping_start、mapping_pause、mapping_resume、mapping_save、mapping_stop 或 null。禁止移动、路径、云台、ROS、shell、/cmd_vel。建图动作必须由本地服务二次确认。"
        messages = [{"role": "system", "content": system}, *history[-8:], {"role": "user", "content": json.dumps({"transcript": transcript, "context": context}, ensure_ascii=False)}]
        if self.wire_api == "responses":
            payload = {"model": self.model, "input": messages, "max_output_tokens": self.max_output_tokens, "temperature": 0}
        else:
            payload = {"model": self.model, "messages": messages, "max_tokens": self.max_output_tokens, "temperature": 0}
        request_id = uuid4().hex[:12]
        for attempt in range(2):
            started = time.monotonic()
            try:
                response = await self._client.post(self.endpoint, json=payload, headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}", "X-Request-ID": request_id})
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
                    # Gateways may wrap text as {"message": ...}, or ignore the
                    # JSON-only instruction. Keep both forms usable as text-only
                    # replies while still rejecting malformed JSON objects.
                    try:
                        parsed = json.loads(content)
                    except json.JSONDecodeError:
                        if content.startswith(("{", "[")):
                            raise
                        decision = AssistantDecision(reply_text=content, action=None, confidence=None)
                    else:
                        if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
                            decision = AssistantDecision(reply_text=parsed["message"], action=None, confidence=None)
                        elif isinstance(parsed, dict):
                            # A gateway may truncate the optional text field and
                            # return only an action. Preserve the validated action
                            # while supplying a short, safe acknowledgement.
                            decision = AssistantDecision.model_validate(
                                {**parsed, "reply_text": parsed.get("reply_text") or "好的。"}
                            )
                        else:
                            raise
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
                logger.warning("assistant provider invalid response type=%s content=%r", type(exc).__name__, content[:500] if isinstance(content, str) else content)
                raise AssistantProviderError("invalid_decision", "助手返回格式无效", False) from exc
            return decision
        raise AssistantProviderError("assistant_unavailable", "助手服务暂时不可用", True)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
