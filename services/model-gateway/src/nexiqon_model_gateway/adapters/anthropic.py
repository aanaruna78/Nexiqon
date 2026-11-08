"""Anthropic Messages API adapter (chat and tool use)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from nexiqon_model_gateway.adapters.http import post_json
from nexiqon_model_gateway.providers import ProviderError
from nexiqon_model_gateway.types import ChatCall, ChatOutput, Message, ToolCall, Usage

ANTHROPIC_BASE = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
STRUCTURED_TOOL = "respond_with_json"  # forced tool used to obtain schema-shaped output


def _blocks(m: Message) -> list[dict[str, Any]] | str:
    if m.role == "tool":
        return [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content or ""}]
    if m.tool_calls:
        blocks: list[dict[str, Any]] = [{"type": "text", "text": m.content}] if m.content else []
        blocks += [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
            for c in m.tool_calls
        ]
        return blocks
    return m.content or ""


class Anthropic:
    name = "anthropic"

    def __init__(self, api_key: str | None, client: httpx.AsyncClient) -> None:
        self._key = api_key
        self._client = client

    async def chat(self, call: ChatCall) -> ChatOutput:
        if not self._key:
            raise ProviderError(self.name, "no API key configured")
        system = "\n\n".join(m.content or "" for m in call.messages if m.role == "system")
        messages = [
            {"role": "user" if m.role in ("user", "tool") else "assistant", "content": _blocks(m)}
            for m in call.messages
            if m.role != "system"
        ]
        body: dict[str, Any] = {
            "model": call.model,
            "max_tokens": call.max_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system
        if call.temperature is not None:
            body["temperature"] = call.temperature
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in call.tools
        ]
        if call.response_schema is not None:
            tools.append(
                {
                    "name": STRUCTURED_TOOL,
                    "description": "Return the final answer.",
                    "input_schema": call.response_schema,
                }
            )
            body["tool_choice"] = {"type": "tool", "name": STRUCTURED_TOOL}
        if tools:
            body["tools"] = tools
        base = (call.base_url or ANTHROPIC_BASE).rstrip("/")
        headers = {"x-api-key": self._key, "anthropic-version": API_VERSION}
        data = await post_json(self._client, self.name, f"{base}/v1/messages", body, headers)
        try:
            text = (
                "".join(b.get("text", "") for b in data["content"] if b["type"] == "text") or None
            )
            calls = [
                ToolCall(id=b["id"], name=b["name"], arguments=b.get("input") or {})
                for b in data["content"]
                if b["type"] == "tool_use"
            ]
            if call.response_schema is not None:
                structured = next((c for c in calls if c.name == STRUCTURED_TOOL), None)
                if structured is not None:
                    text, calls = (
                        json.dumps(structured.arguments),
                        [c for c in calls if c.name != STRUCTURED_TOOL],
                    )
            usage = data.get("usage") or {}
            stop = data.get("stop_reason") or "end_turn"
            return ChatOutput(
                content=text,
                tool_calls=calls,
                finish_reason={
                    "end_turn": "stop",
                    "tool_use": "tool_calls",
                    "max_tokens": "length",
                }.get(stop, stop),
                usage=Usage(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                ),
                model=data.get("model", call.model),
            )
        except (KeyError, TypeError) as exc:
            raise ProviderError(self.name, f"unexpected response shape: {exc}") from exc
