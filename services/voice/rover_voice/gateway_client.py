from __future__ import annotations
import httpx


class GatewayError(RuntimeError):
    pass


class GatewayClient:
    def __init__(self, base_url: str, token: str, client: httpx.AsyncClient | None = None):
        if not (base_url.startswith("http://127.0.0.1") or base_url.startswith("http://[::1]")):
            raise ValueError("gateway must be loopback")
        self.base_url, self.token = base_url.rstrip("/"), token
        self.client = client or httpx.AsyncClient(timeout=20)
        self._owns = client is None

    async def assistant(self, request):
        try:
            response = await self.client.post(f"{self.base_url}/assistant", json=request.model_dump(mode="json"), headers={"X-Rover-Voice-Token": self.token})
            if response.status_code >= 400:
                raise GatewayError("assistant_unavailable")
            from pydantic import TypeAdapter
            from app.models.assistant import VoiceAssistantResponse
            return TypeAdapter(VoiceAssistantResponse).validate_python(response.json())
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise GatewayError("assistant_unavailable") from exc

    async def heartbeat(self, status) -> None:
        try:
            await self.client.post(f"{self.base_url}/heartbeat", json=status.model_dump(mode="json"), headers={"X-Rover-Voice-Token": self.token})
        except httpx.HTTPError:
            return

    async def close(self):
        if self._owns:
            await self.client.aclose()
