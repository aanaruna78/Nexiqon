"""Google Gemini (generateContent) adapter: chat and function calling.

JSON-schema output uses ``responseJsonSchema``; this is validated against the live API in the
model bake-off (M-07) like every adapter.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from nexiqon_model_gateway.adapters.http import post_json
from nexiqon_model_gateway.providers import ProviderError
from nexiqon_model_gateway.types import ChatCall, ChatOutput, Message, ToolCall, Usage

GEMINI_BASE = "https://generativelanguage.googleapis.com"


def _content(m: Message) -> dict[str, Any]:
    if m.role == "tool":
        return {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": m.tool_call_id or "tool",
                        "response": {"content": m.content},
                    }
                }
            ],
        }
    parts: list[dict[str, Any]] = [{"text": m.content}] if m.content else []
    parts += [{"functionCall": {"name": c.name, "args": c.arguments}} for c in m.tool_calls or []]
    return {"role": "model" if m.role == "assistant" else "user", "parts": parts}


class Gemini:
    name = "gemini"

    def __init__(self, api_key: str | None, client: httpx.AsyncClient) -> None:
        self._key = api_key
        self._client = client

    async def chat(self, call: ChatCall) -> ChatOutput:
        if not self._key:
            raise ProviderError(self.name, "no API key configured")
        system = "\n\n".join(m.content or "" for m in call.messages if m.role == "system")
        body: dict[str, Any] = {
            "contents": [_content(m) for m in call.messages if m.role != "system"]
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        config: dict[str, Any] = {"maxOutputTokens": call.max_tokens}
        if call.temperature is not None:
            config["temperature"] = call.temperature
        if call.response_schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = call.response_schema
        body["generationConfig"] = config
        if call.tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {"name": t.name, "description": t.description, "parameters": t.parameters}
                        for t in call.tools
                    ]
                }
            ]
        base = (call.base_url or GEMINI_BASE).rstrip("/")
        url = f"{base}/v1beta/models/{call.model}:generateContent"
        data = await post_json(self._client, self.name, url, body, {"x-goog-api-key": self._key})
        try:
            candidate = data["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts) or None
            calls = [
                ToolCall(
                    id=f"call_{uuid.uuid4().hex[:12]}",
                    name=p["functionCall"]["name"],
                    arguments=p["functionCall"].get("args") or {},
                )
                for p in parts
                if "functionCall" in p
            ]
            meta = data.get("usageMetadata") or {}
            reason = candidate.get("finishReason", "STOP")
            return ChatOutput(
                content=text,
                tool_calls=calls,
                finish_reason="tool_calls"
                if calls
                else {"STOP": "stop", "MAX_TOKENS": "length"}.get(reason, reason.lower()),
                usage=Usage(
                    input_tokens=meta.get("promptTokenCount", 0),
                    output_tokens=meta.get("candidatesTokenCount", 0),
                ),
                model=call.model,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, f"unexpected response shape: {exc}") from exc
