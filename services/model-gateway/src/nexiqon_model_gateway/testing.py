"""A fake model-provider network for tests: records every request, answers like each provider."""

from __future__ import annotations

import json
from typing import Any

import httpx

DIMS = 1024


class FakeProviders:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail: dict[str, int] = {}  # host -> HTTP status to return
        self.dims = DIMS

    @property
    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]

    def bodies(self, host: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.host == host]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host in self.fail:
            return httpx.Response(self.fail[host], json={"error": {"message": "provider says no"}})
        body = json.loads(request.content)
        if body.get("stream"):
            return self._stream(path, body)
        if path.endswith("/chat/completions"):
            last = body["messages"][-1]["content"]
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": f"You said: {last}"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                },
            )
        if path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "data": [
                        {"index": i, "embedding": [0.01] * self.dims}
                        for i in range(len(body["input"]))
                    ],
                    "usage": {"prompt_tokens": 7 * len(body["input"])},
                },
            )
        if path.endswith("/rerank"):
            docs = body["documents"]
            scores = [
                {"index": i, "relevance_score": 1.0 if body["query"] in d else 0.1}
                for i, d in enumerate(docs)
            ]
            return httpx.Response(200, json={"model": body["model"], "results": scores})
        if path.endswith("/v1/messages"):
            last = body["messages"][-1]["content"]
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "content": [{"type": "text", "text": f"Backup says: {last}"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 80, "output_tokens": 20},
                },
            )
        return httpx.Response(404, json={"error": "unknown fake route"})

    def _stream(self, path: str, body: dict[str, Any]) -> httpx.Response:
        """Server-sent events in 3-character pieces (so redaction placeholders get split)."""
        last = body["messages"][-1]["content"]
        text = f"You said: {last}" if path.endswith("/chat/completions") else f"Backup says: {last}"
        pieces = [text[i : i + 3] for i in range(0, len(text), 3)]
        events: list[dict[str, Any]]
        if path.endswith("/chat/completions"):
            events = [
                {"choices": [{"delta": {"content": p}, "finish_reason": None}]} for p in pieces
            ]
            events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            events.append({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
            lines = [f"data: {json.dumps(e)}" for e in events] + ["data: [DONE]"]
        else:
            events = [{"type": "message_start", "message": {"usage": {"input_tokens": 80}}}]
            events += [
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": p}}
                for p in pieces
            ]
            events.append(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 20},
                }
            )
            lines = [f"event: {e['type']}\ndata: {json.dumps(e)}" for e in events]
        return httpx.Response(
            200, content="\n\n".join(lines).encode(), headers={"content-type": "text/event-stream"}
        )
