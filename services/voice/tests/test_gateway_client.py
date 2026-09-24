import asyncio
import json

import httpx

from rover_voice.contracts import VoiceAssistantRequest
from rover_voice.gateway_client import GatewayClient, GatewayError


def test_gateway_sends_only_transcript_metadata_and_parses_response():
    async def run():
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = dict(request.headers)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"state": "completed", "reply_text": "收到。", "action": None})

        transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = GatewayClient("http://127.0.0.1:8000/api/v1/voice", "voice-token", transport_client)
        response = await gateway.assistant(VoiceAssistantRequest("session", "turn", "当前状态"))
        await gateway.close()
        await transport_client.aclose()
        assert response.reply_text == "收到。"
        assert seen["headers"]["x-rover-voice-token"] == "voice-token"
        assert seen["body"]["transcript"] == "当前状态"
        assert "audio" not in seen["body"]
        assert "api_key" not in seen["body"]

    asyncio.run(run())


def test_gateway_rejects_invalid_response_without_leaking_body():
    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"reply_text": ""})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = GatewayClient("http://127.0.0.1:8000/api/v1/voice", "token", client)
        try:
            try:
                await gateway.assistant(VoiceAssistantRequest("session", "turn", "状态"))
            except GatewayError as exc:
                assert str(exc) == "assistant_invalid_response"
            else:
                raise AssertionError("invalid response must be rejected")
        finally:
            await gateway.close()
            await client.aclose()

    asyncio.run(run())


def test_gateway_rejects_non_loopback_urls():
    try:
        GatewayClient("http://127.0.0.1.evil.example/api/v1/voice", "token")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback gateway must be rejected")
