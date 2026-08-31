import asyncio
import json

import httpx
from pydantic import SecretStr

from app.services.assistant_provider import OpenAICompatibleAssistantProvider


def test_responses_output_text_message_is_normalized_to_assistant_decision():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-5.6-sol"
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "reasoning", "content": []},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"message":"测试成功"}'}],
                    },
                ]
            },
        )

    async def run() -> str:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleAssistantProvider(
            "https://gmn.chuangzuoli.com/v1",
            SecretStr("test-key"),
            model="gpt-5.6-sol",
            wire_api="responses",
            transport=client,
        )
        decision = await provider.decide("请回复测试成功", {}, [])
        await provider.close()
        await client.aclose()
        return decision.reply_text

    assert asyncio.run(run()) == "测试成功"


def test_responses_plain_output_text_is_usable_as_reply():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": "普通文本回复"})

    async def run() -> str:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleAssistantProvider(
            "https://gmn.chuangzuoli.com/v1",
            SecretStr("test-key"),
            model="gpt-5.6-sol",
            wire_api="responses",
            transport=client,
        )
        decision = await provider.decide("请回复", {}, [])
        await provider.close()
        await client.aclose()
        return decision.reply_text

    assert asyncio.run(run()) == "普通文本回复"


def test_responses_action_only_payload_gets_safe_text_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": '{"action":null}'})

    async def run() -> str:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleAssistantProvider(
            "https://gmn.chuangzuoli.com/v1",
            SecretStr("test-key"),
            model="gpt-5.6-sol",
            wire_api="responses",
            transport=client,
        )
        decision = await provider.decide("请回复", {}, [])
        await provider.close()
        await client.aclose()
        return decision.reply_text

    assert asyncio.run(run()) == "好的。"
