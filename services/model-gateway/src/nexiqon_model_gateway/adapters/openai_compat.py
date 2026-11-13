"""OpenAI-compatible adapter: OpenAI itself, vLLM and Ollama (chat, embeddings, rerank)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexiqon_model_gateway.adapters.http import post_json, stream_sse
from nexiqon_model_gateway.providers import ProviderError
from nexiqon_model_gateway.types import (
    ChatCall,
    ChatChunk,
    ChatOutput,
    EmbedCall,
    EmbedOutput,
    Message,
    RerankCall,
    RerankOutput,
    ToolCall,
    Usage,
)

OPENAI_BASE = "https://api.openai.com/v1"
# Qwen3-Embedding expects an instruction on queries (not on documents) for best retrieval quality.
QWEN_QUERY_INSTRUCTION = "Instruct: Given a question, retrieve passages that answer it\nQuery: "


def _message(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in m.tool_calls
        ]
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    return out


class OpenAICompatible:
    """``name`` is "openai" (hosted OpenAI) or "openai_compatible" (vLLM, Ollama, others)."""

    def __init__(self, name: str, api_key: str | None, client: httpx.AsyncClient) -> None:
        self.name = name
        self._key = api_key
        self._client = client

    def _base(self, base_url: str | None) -> str:
        if self.name == "openai":
            return (base_url or OPENAI_BASE).rstrip("/")
        if not base_url:
            raise ProviderError(self.name, "profile has no base_url for this provider")
        return base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"} if self._key else {}

    def _request(self, call: ChatCall) -> tuple[str, dict[str, Any], dict[str, str]]:
        body: dict[str, Any] = {
            "model": call.model,
            "messages": [_message(m) for m in call.messages],
        }
        body["max_completion_tokens" if self.name == "openai" else "max_tokens"] = call.max_tokens
        if call.temperature is not None:
            body["temperature"] = call.temperature
        if call.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in call.tools
            ]
        if call.response_schema is not None:
            if call.json_schema_supported:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "output",
                        "schema": call.response_schema,
                        "strict": True,
                    },
                }
            else:
                # Weaker local models: vLLM constrained decoding guarantees schema-valid JSON.
                body["guided_json"] = call.response_schema
        return f"{self._base(call.base_url)}/chat/completions", body, self._headers()

    async def chat(self, call: ChatCall) -> ChatOutput:
        url, body, headers = self._request(call)
        data = await post_json(self._client, self.name, url, body, headers)
        try:
            choice = data["choices"][0]
            message = choice["message"]
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"].get("arguments") or "{}"),
                )
                for tc in message.get("tool_calls") or []
            ]
            usage = data.get("usage") or {}
            return ChatOutput(
                content=message.get("content"),
                tool_calls=tool_calls,
                finish_reason=choice.get("finish_reason") or "stop",
                usage=Usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                ),
                model=data.get("model", call.model),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(self.name, f"unexpected chat response shape: {exc}") from exc

    async def chat_stream(self, call: ChatCall) -> AsyncIterator[ChatChunk]:
        url, body, headers = self._request(call)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        usage = Usage()
        finish: str | None = None
        async for data in stream_sse(self._client, self.name, url, body, headers):
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except ValueError:
                continue
            if event.get("usage"):
                u = event["usage"]
                usage = Usage(
                    input_tokens=u.get("prompt_tokens", 0),
                    output_tokens=u.get("completion_tokens", 0),
                )
            for choice in event.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield ChatChunk(text=text)
                finish = choice.get("finish_reason") or finish
        yield ChatChunk(usage=usage, finish_reason=finish or "stop", model=call.model)

    async def embed(self, call: EmbedCall) -> EmbedOutput:
        inputs = call.inputs
        if call.input_type == "query" and "qwen3-embedding" in call.model.lower():
            inputs = [QWEN_QUERY_INSTRUCTION + text for text in inputs]
        body: dict[str, Any] = {"model": call.model, "input": inputs, "encoding_format": "float"}
        if self.name == "openai":
            body["dimensions"] = call.dimensions  # text-embedding-3 supports shortening
        data = await post_json(
            self._client,
            self.name,
            f"{self._base(call.base_url)}/embeddings",
            body,
            self._headers(),
        )
        try:
            rows = sorted(data["data"], key=lambda r: r["index"])
            usage = data.get("usage") or {}
            return EmbedOutput(
                vectors=[r["embedding"] for r in rows],
                usage=Usage(input_tokens=usage.get("prompt_tokens", 0)),
                model=data.get("model", call.model),
            )
        except (KeyError, TypeError) as exc:
            raise ProviderError(self.name, f"unexpected embeddings response shape: {exc}") from exc

    async def rerank(self, call: RerankCall) -> RerankOutput:
        body = {
            "model": call.model,
            "query": call.query,
            "documents": call.documents,
            "top_n": call.top_n,
        }
        data = await post_json(
            self._client, self.name, f"{self._base(call.base_url)}/rerank", body, self._headers()
        )
        try:
            results = [(int(r["index"]), float(r["relevance_score"])) for r in data["results"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(self.name, f"unexpected rerank response shape: {exc}") from exc
        results.sort(key=lambda r: r[1], reverse=True)
        return RerankOutput(results=results[: call.top_n], model=data.get("model", call.model))
