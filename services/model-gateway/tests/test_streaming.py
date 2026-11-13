"""Streamed chat (CH-01 groundwork): same checks as /v1/chat, text arrives in pieces."""

from __future__ import annotations

import json
from typing import Any

import pytest

from .conftest import StackFactory

pytestmark = pytest.mark.integration
USER = [{"role": "user", "content": "What is the retention period?"}]


def events(response: Any) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_stream_delivers_the_whole_answer_then_usage(make_stack: StackFactory) -> None:
    s = make_stack()
    r = s.gateway.post("/v1/chat/stream", json={"messages": USER}, headers=s.tenants.a.headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    got = events(r)
    deltas = [d["text"] for kind, d in got if kind == "delta"]
    assert len(deltas) > 5
    assert "".join(deltas) == "You said: What is the retention period?"
    kind, done = got[-1]
    assert kind == "done"
    assert done["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert float(done["cost_usd"]) > 0
    assert done["route"]["provider"] == "openai"
    report = s.gateway.get("/v1/usage", headers=s.tenants.a.headers).json()
    assert report["rows"][0]["calls"] == 1


def test_redaction_survives_placeholders_split_across_chunks(make_stack: StackFactory) -> None:
    s = make_stack()
    msg = [{"role": "user", "content": "Mail jane@example.com today"}]
    r = s.gateway.post("/v1/chat/stream", json={"messages": msg}, headers=s.tenants.a.headers)
    text = "".join(d["text"] for kind, d in events(r) if kind == "delta")
    assert text == "You said: Mail jane@example.com today"
    sent = s.providers.bodies("api.openai.com")[0]["messages"][0]["content"]
    assert sent == "Mail [EMAIL_1] today"


def test_fallback_before_the_first_chunk(make_stack: StackFactory) -> None:
    s = make_stack()
    s.providers.fail["api.openai.com"] = 503
    got = events(
        s.gateway.post("/v1/chat/stream", json={"messages": USER}, headers=s.tenants.a.headers)
    )
    assert "".join(d["text"] for kind, d in got if kind == "delta").startswith("Backup says:")
    assert got[-1][1]["route"]["fallback_used"] is True


def test_refusals_are_plain_http_errors(make_stack: StackFactory) -> None:
    s = make_stack()
    s.deploy_profile(
        "cloud-only",
        {
            "chat": {"provider": "openai", "model": "gpt-4.1"},
            "embedding": {
                "provider": "openai",
                "model": "text-embedding-3-small",
                "dimensions": 1024,
            },
            "data_policy": {"location": "cloud", "allow_training": False},
        },
        s.tenants.a.headers,
    )
    r = s.gateway.post(
        "/v1/chat/stream",
        json={"profile": "cloud-only", "messages": USER, "classification": "restricted"},
        headers=s.tenants.a.headers,
    )
    assert r.status_code == 403
    assert s.providers.requests == []
    tools = s.gateway.post(
        "/v1/chat/stream",
        json={"messages": USER, "tools": [{"name": "x"}]},
        headers=s.tenants.a.headers,
    )
    assert tools.status_code == 400


def test_offline_provider_streams(make_stack: StackFactory) -> None:
    s = make_stack(allow_offline_provider=True)
    prompt = "Sources:\n\n[1] Guide > Backups\nBackups are kept for 35 days.\n\nQuestion: How long are backups kept?"
    got = events(
        s.gateway.post(
            "/v1/chat/stream",
            json={"profile": "dev-offline", "messages": [{"role": "user", "content": prompt}]},
            headers=s.tenants.a.headers,
        )
    )
    assert (
        "".join(d["text"] for kind, d in got if kind == "delta")
        == "Backups are kept for 35 days. [1]"
    )
