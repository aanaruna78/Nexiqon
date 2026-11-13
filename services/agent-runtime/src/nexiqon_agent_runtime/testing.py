"""Test doubles for the services agent-runtime calls (model gateway, retrieval, ingestion)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

SEP = chr(0x203A)  # section separator used in citations


class FakeServices:
    """One handler for model-gateway, retrieval and ingestion hosts; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.intents: dict[str, str] = {}  # question substring -> intent the "model" returns
        self.passages: list[dict[str, Any]] = [
            {
                "id": str(uuid.uuid4()),
                "document_id": str(uuid.uuid4()),
                "citation": "Admin Guide " + SEP + " Teammates",
                "text": "Open Settings, then Members, and choose Invite to add a teammate.",
                "classification": "internal",
                "title": "Admin Guide",
                "heading_path": ["Teammates"],
                "source_uri": "upload://admin.md",
                "score": 0.9,
            }
        ]
        self.abstain = False
        self.collections = {"product-docs": str(uuid.uuid4())}
        self.answer = "Open Settings, then Members, and choose Invite [1]."
        # Tool gateway: published tools (public definitions) and what the "model" extracts.
        self.tools: dict[str, dict[str, Any]] = {}
        self.tool_args: dict[str, Any] = {}
        self.tool_result: dict[str, Any] = {"plan": "Team", "status": "active"}
        # Red-team (AG-03): an "obedient" model. When it sees ``attack`` anywhere in what it is
        # sent (outside the system prompt) it writes ``obeyed`` ({system} = the system prompt).
        self.attacks: list[tuple[str, str]] = []

    def chats(self, kind: str | None = None) -> list[dict[str, Any]]:
        return [
            b for k, b in self.calls if k == "chat" and (kind is None or b.get("_kind") == kind)
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        body = json.loads(request.content) if request.content else {}
        if host == "model-gateway" and path == "/v1/chat":
            return self._chat(body)
        if host == "model-gateway" and path == "/v1/chat/stream":
            return self._chat_stream(body)
        if host == "retrieval" and path == "/v1/search":
            self.calls.append(("search", body))
            return httpx.Response(
                200,
                json={
                    "passages": [] if self.abstain else self.passages,
                    "abstain": self.abstain,
                    "evidence_score": 0.1 if self.abstain else 0.8,
                    "embedding_model": "fake",
                    "reranked": False,
                    "timings_ms": {"total": 5.0},
                },
            )
        if host == "retrieval" and path == "/v1/citations/verify":
            self.calls.append(("verify", body))
            return httpx.Response(
                200,
                json={
                    "answer": body["answer"],
                    "citations": body["citations"],
                    "removed": [],
                    "supported_sentences": 1,
                    "cited_sentences": 1,
                    "abstain": not body["citations"],
                },
            )
        if host == "tool-gateway":
            return self._tools(request.method, path, body)
        if host == "ingestion" and path == "/v1/collections":
            self.calls.append(("collections", {}))
            return httpx.Response(
                200, json=[{"name": n, "id": i} for n, i in self.collections.items()]
            )
        return httpx.Response(404, json={"detail": f"no fake for {host}{path}"})

    def _tools(self, method: str, path: str, body: dict[str, Any]) -> httpx.Response:
        parts = path.strip("/").split("/")
        if method == "GET" and parts[:2] == ["v1", "tools"]:
            tool = self.tools.get(parts[2])
            return (
                httpx.Response(200, json=tool)
                if tool
                else httpx.Response(404, json={"detail": "not found"})
            )
        if parts[-1] == "approvals":
            self.calls.append(("confirm", {"tool": parts[2], **body}))
            return httpx.Response(
                201,
                json={
                    "id": "11111111-1111-1111-1111-111111111111",
                    "summary": f"{parts[2]} {body['arguments']}",
                    "status": "pending",
                },
            )
        if parts[-1] == "decision":
            self.calls.append(("decide", {"approval_id": parts[2], **body}))
            return httpx.Response(
                200, json={"id": parts[2], "status": "approved" if body["approved"] else "declined"}
            )
        if parts[-1] == "invoke":
            self.calls.append(("invoke", {"tool": parts[2], **body}))
            return httpx.Response(
                200,
                json={
                    "call_id": None,
                    "ok": True,
                    "result": self.tool_result,
                    "classification": "confidential",
                },
            )
        return httpx.Response(404, json={"detail": "no fake"})

    def _chat_stream(self, body: dict[str, Any]) -> httpx.Response:
        """The same reply as ``_chat``, as server-sent events of a few characters each."""
        reply = self._chat({**body, "_stream": True}).json()
        text = reply["content"]
        events = [
            f"event: delta\ndata: {json.dumps({'text': text[i : i + 4]})}"
            for i in range(0, len(text), 4)
        ]
        done = {"done": True, "route": reply["route"], "usage": reply["usage"], "cost_usd": "0"}
        events.append(f"event: done\ndata: {json.dumps(done)}")
        return httpx.Response(
            200,
            content=("\n\n".join(events) + "\n\n").encode(),
            headers={"content-type": "text/event-stream"},
        )

    def _chat(self, body: dict[str, Any]) -> httpx.Response:
        messages = body["messages"]
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        last = messages[-1]["content"]
        if system.startswith("Extract the arguments"):
            kind, content = "extract", json.dumps(self.tool_args)
        elif system.startswith("Classify"):
            kind = "classify"
            intent = next(
                (v for k, v in self.intents.items() if k.lower() in last.lower()), "unclear"
            )
            content = json.dumps({"intent": intent})
        elif last.startswith("Sources:"):
            kind, content = "answer", self.answer
        elif last.startswith("Ask one short question"):
            kind, content = "clarify", "Which part of the product do you mean?"
        elif last.startswith("Summarise this conversation"):
            kind, content = "summary", "Customer wants help; documentation did not cover it."
        else:
            kind, content = "smalltalk", "Hello! How can I help?"
        seen = "\n".join(m["content"] or "" for m in messages if m["role"] != "system")
        for attack, obeyed in self.attacks:
            if kind in ("answer", "smalltalk") and attack in seen:
                content = obeyed.replace("{system}", system)
        self.calls.append(("chat", {**body, "_kind": kind}))
        return httpx.Response(
            200,
            json={
                "content": content,
                "tool_calls": [],
                "finish_reason": "stop",
                "route": {"profile": body["profile"], "model": "fake-model", "provider": "fake"},
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "cost_usd": "0",
            },
        )


class HostRouter(httpx.AsyncBaseTransport):
    """Routes by host: ASGI apps for real services, a handler for the fakes."""

    def __init__(
        self, routes: dict[str, httpx.AsyncBaseTransport], default: httpx.AsyncBaseTransport
    ) -> None:
        self.routes = routes
        self.default = default

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.routes.get(request.url.host, self.default).handle_async_request(request)
