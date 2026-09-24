from __future__ import annotations

import httpx
from dataclasses import dataclass
from urllib.parse import urlsplit

from .contracts import VoiceAssistantRequest, VoiceStatus


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayResponse:
    reply_text: str
    state: str = "completed"
    action: dict[str, object] | None = None
    error: dict[str, object] | None = None


class GatewayClient:
    """Authenticated loopback client; it sends transcript/status metadata only."""

    def __init__(self, base_url: str, token: str, client: httpx.AsyncClient | None = None):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
            raise ValueError("gateway must be loopback HTTP")
        if not token:
            raise ValueError("gateway token is required")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=3.0))
        self._owns = client is None

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Rover-Voice-Token": self._token}

    async def assistant(self, request: VoiceAssistantRequest) -> GatewayResponse:
        try:
            response = await self.client.post(
                f"{self.base_url}/assistant",
                json=request.model_dump(mode="json"),
                headers=self._headers,
            )
            if response.status_code >= 400:
                raise GatewayError("assistant_unavailable")
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("reply_text"), str):
                raise GatewayError("assistant_invalid_response")
            reply = body["reply_text"].strip()
            if not reply or len(reply) > 2000:
                raise GatewayError("assistant_invalid_response")
            state = body.get("state", "completed")
            if state not in {"completed", "awaiting_confirmation", "executed", "rejected", "unavailable"}:
                raise GatewayError("assistant_invalid_response")
            return GatewayResponse(
                reply_text=reply,
                state=state,
                action=body.get("action") if isinstance(body.get("action"), dict) else None,
                error=body.get("error") if isinstance(body.get("error"), dict) else None,
            )
        except GatewayError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise GatewayError("assistant_unavailable") from exc

    async def heartbeat(self, status: VoiceStatus) -> None:
        try:
            response = await self.client.post(
                f"{self.base_url}/heartbeat",
                json=status.model_dump(mode="json"),
                headers=self._headers,
            )
            if response.status_code >= 400:
                raise GatewayError("heartbeat_unavailable")
        except (httpx.HTTPError, GatewayError):
            # A heartbeat must never stop local wake word/ASR processing.
            return

    async def next_tts(self) -> str | None:
        try:
            response = await self.client.get(f"{self.base_url}/tts/next", headers=self._headers)
            if response.status_code >= 400:
                return None
            body = response.json()
            text = body.get("text") if isinstance(body, dict) else None
            return text.strip() if isinstance(text, str) and text.strip() else None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    async def close(self) -> None:
        if self._owns:
            await self.client.aclose()
