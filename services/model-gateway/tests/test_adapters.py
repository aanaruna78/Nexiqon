"""Provider adapters against recorded wire shapes (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from nexiqon_model_gateway.adapters.anthropic import STRUCTURED_TOOL, Anthropic
from nexiqon_model_gateway.adapters.gemini import Gemini
from nexiqon_model_gateway.adapters.openai_compat import QWEN_QUERY_INSTRUCTION, OpenAICompatible
from nexiqon_model_gateway.providers import ProviderError
from nexiqon_model_gateway.types import (
    ChatCall,
    EmbedCall,
    Message,
    RerankCall,
    ToolCall,
    ToolSpec,
)

Handler = Any


def client(
    reply: dict[str, Any], seen: list[httpx.Request], status: int = 200
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=reply)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def body(request: httpx.Request) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(request.content)
    return data


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
OPENAI_REPLY = {
    "model": "gpt-4.1",
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"q": "x"}'},
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
}


async def test_openai_chat_uses_current_parameters_and_parses_tool_calls() -> None:
    seen: list[httpx.Request] = []
    adapter = OpenAICompatible("openai", "sk-x", client(OPENAI_REPLY, seen))
    out = await adapter.chat(
        ChatCall(
            model="gpt-4.1",
            messages=[Message(role="user", content="hi")],
            tools=[ToolSpec(name="lookup")],
            response_schema=SCHEMA,
            max_tokens=99,
        )
    )
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-x"
    sent = body(req)
    assert sent["max_completion_tokens"] == 99
    assert "max_tokens" not in sent
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["tools"][0]["function"]["name"] == "lookup"
    assert out.tool_calls == [ToolCall(id="call_1", name="lookup", arguments={"q": "x"})]
    assert out.finish_reason == "tool_calls"
    assert (out.usage.input_tokens, out.usage.output_tokens) == (12, 3)


async def test_vllm_uses_max_tokens_and_guided_json_for_weaker_models() -> None:
    seen: list[httpx.Request] = []
    reply = {**OPENAI_REPLY, "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    adapter = OpenAICompatible("openai_compatible", None, client(reply, seen))
    await adapter.chat(
        ChatCall(
            model="qwen3-8b",
            base_url="http://vllm:8000/v1/",
            messages=[Message(role="user", content="hi")],
            response_schema=SCHEMA,
            json_schema_supported=False,
            max_tokens=50,
        )
    )
    sent = body(seen[0])
    assert str(seen[0].url) == "http://vllm:8000/v1/chat/completions"
    assert "authorization" not in seen[0].headers
    assert sent["max_tokens"] == 50
    assert sent["guided_json"] == SCHEMA
    assert "response_format" not in sent


async def test_compatible_provider_requires_base_url() -> None:
    adapter = OpenAICompatible("openai_compatible", None, client({}, []))
    with pytest.raises(ProviderError, match="base_url"):
        await adapter.chat(ChatCall(model="m", messages=[Message(role="user", content="x")]))


async def test_embeddings_dimensions_and_qwen_query_instruction() -> None:
    seen: list[httpx.Request] = []
    reply = {"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]}
    openai = OpenAICompatible("openai", "k", client(reply, seen))
    out = await openai.embed(
        EmbedCall(model="text-embedding-3-small", inputs=["a", "b"], dimensions=1024)
    )
    assert out.vectors == [[1.0], [2.0]]  # re-ordered by index
    assert body(seen[0])["dimensions"] == 1024
    local = OpenAICompatible("openai_compatible", None, client(reply, seen))
    await local.embed(
        EmbedCall(
            model="qwen3-embedding-0.6b",
            base_url="http://e/v1",
            inputs=["a", "b"],
            dimensions=1024,
            input_type="query",
        )
    )
    sent = body(seen[1])
    assert "dimensions" not in sent
    assert sent["input"][0] == QWEN_QUERY_INSTRUCTION + "a"


async def test_rerank_sorted_and_trimmed() -> None:
    seen: list[httpx.Request] = []
    reply = {
        "results": [
            {"index": 0, "relevance_score": 0.1},
            {"index": 1, "relevance_score": 0.9},
            {"index": 2, "relevance_score": 0.5},
        ]
    }
    adapter = OpenAICompatible("openai_compatible", None, client(reply, seen))
    out = await adapter.rerank(
        RerankCall(model="r", base_url="http://r/v1", query="q", documents=["a", "b", "c"], top_n=2)
    )
    assert out.results == [(1, 0.9), (2, 0.5)]
    assert str(seen[0].url) == "http://r/v1/rerank"


async def test_anthropic_messages_system_tools_and_structured_output() -> None:
    seen: list[httpx.Request] = []
    reply = {
        "model": "claude-sonnet-5-5",
        "content": [
            {"type": "tool_use", "id": "t1", "name": STRUCTURED_TOOL, "input": {"answer": "42"}}
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    adapter = Anthropic("sk-ant", client(reply, seen))
    out = await adapter.chat(
        ChatCall(
            model="claude-sonnet-5-5",
            messages=[
                Message(role="system", content="Be brief."),
                Message(role="user", content="q"),
                Message(
                    role="assistant",
                    tool_calls=[ToolCall(id="t0", name="lookup", arguments={"q": 1})],
                ),
                Message(role="tool", tool_call_id="t0", content="result"),
            ],
            response_schema=SCHEMA,
            max_tokens=64,
        )
    )
    req = seen[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "sk-ant"
    assert req.headers["anthropic-version"] == "2023-06-01"
    sent = body(req)
    assert sent["system"] == "Be brief."
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "user"]
    assert sent["messages"][2]["content"][0]["type"] == "tool_result"
    assert sent["tool_choice"] == {"type": "tool", "name": STRUCTURED_TOOL}
    assert json.loads(out.content or "") == {"answer": "42"}
    assert out.tool_calls == []


async def test_gemini_generate_content_and_function_calls() -> None:
    seen: list[httpx.Request] = []
    reply = {
        "candidates": [
            {
                "content": {"parts": [{"functionCall": {"name": "lookup", "args": {"q": "x"}}}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 2},
    }
    adapter = Gemini("g-key", client(reply, seen))
    out = await adapter.chat(
        ChatCall(
            model="gemini-2.5-flash",
            messages=[Message(role="system", content="sys"), Message(role="user", content="hi")],
            tools=[ToolSpec(name="lookup")],
        )
    )
    req = seen[0]
    assert req.url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert req.headers["x-goog-api-key"] == "g-key"
    sent = body(req)
    assert sent["systemInstruction"]["parts"][0]["text"] == "sys"
    assert sent["tools"][0]["functionDeclarations"][0]["name"] == "lookup"
    assert out.tool_calls[0].name == "lookup"
    assert out.finish_reason == "tool_calls"
    assert out.usage.input_tokens == 9


@pytest.mark.parametrize(
    ("status", "retryable"), [(429, True), (503, True), (400, False), (401, False)]
)
async def test_http_errors_are_classified(status: int, retryable: bool) -> None:
    adapter = OpenAICompatible("openai", "k", client({"error": "x"}, [], status=status))
    with pytest.raises(ProviderError) as info:
        await adapter.chat(ChatCall(model="m", messages=[Message(role="user", content="x")]))
    assert info.value.retryable is retryable
    assert info.value.status == status


async def test_missing_keys_fail_before_any_request() -> None:
    seen: list[httpx.Request] = []
    for adapter in (Anthropic(None, client({}, seen)), Gemini(None, client({}, seen))):
        with pytest.raises(ProviderError, match="no API key"):
            await adapter.chat(ChatCall(model="m", messages=[Message(role="user", content="x")]))
    assert seen == []
