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
    def __init__(self, base_url: str, api_key: SecretStr, model: str = "gpt-5.6", timeout_seconds: float = 20.0, max_output_tokens: int = 512, transport: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens
        self._client = transport or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=5.0))
        self._owns_client = transport is None

    @property
    def endpoint(self) -> str:
        return self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"

    async def decide(self, transcript: str, context: dict[str, object], history: list[dict[str, str]]) -> AssistantDecision:
        system = "你是贾维斯机器人助手。只能返回 JSON，action 只能是 mapping_start、mapping_pause、mapping_resume、mapping_save、mapping_stop 或 null。禁止移动、路径、云台、ROS、shell、/cmd_vel。建图动作必须由本地服务二次确认。"
        payload = {"model": self.model, "messages": [{"role": "system", "content": system}, *history[-8:], {"role": "user", "content": json.dumps({"transcript": transcript, "context": context}, ensure_ascii=False)}], "max_tokens": self.max_output_tokens, "temperature": 0}
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
                raise AssistantProviderError("assistant_unavailable", "助手认证失败", False)
            if response.status_code >= 400:
                raise AssistantProviderError("assistant_unavailable", "助手请求失败", True)
            try:
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                decision = AssistantDecision.model_validate_json(content)
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
                raise AssistantProviderError("invalid_decision", "助手返回格式无效", False) from exc
            self._validate(decision)
            return decision
        raise AssistantProviderError("assistant_unavailable", "助手服务暂时不可用", True)

    @staticmethod
    def _validate(decision: AssistantDecision) -> None:
        text = decision.reply_text.lower()
        forbidden = ("cmd_vel", "ros2", "shell", "topic", "service", "云台", "移动", "路径")
        if any(token in text for token in forbidden):
            raise AssistantProviderError("invalid_decision", "助手返回包含不支持的控制指令", False)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
