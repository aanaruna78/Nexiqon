"""The offline development provider: off by default, end to end when enabled."""

from __future__ import annotations

import pytest

from .conftest import StackFactory

pytestmark = pytest.mark.integration
PROMPT = "Sources:\n\n[1] Guide > Backups\nBackups are kept for 35 days.\n\nQuestion: How long are backups kept?"


def test_offline_provider_is_refused_unless_enabled(make_stack: StackFactory) -> None:
    s = make_stack()
    r = s.gateway.post(
        "/v1/embeddings",
        json={"profile": "dev-offline", "inputs": ["x"]},
        headers=s.tenants.a.headers,
    )
    assert r.status_code == 400
    assert "offline" in r.json()["detail"]


def test_offline_provider_serves_embeddings_rerank_and_extractive_chat(
    make_stack: StackFactory,
) -> None:
    s = make_stack(allow_offline_provider=True)
    h = s.tenants.a.headers
    emb = s.gateway.post(
        "/v1/embeddings", json={"profile": "dev-offline", "inputs": ["a b", "c"]}, headers=h
    )
    assert emb.status_code == 200, emb.text
    assert emb.json()["dimensions"] == 1024
    assert emb.json()["route"]["model"] == "hash-ngram-1024"
    ranked = s.gateway.post(
        "/v1/rerank",
        json={
            "profile": "dev-offline",
            "query": "backups kept",
            "documents": ["weather", "backups are kept"],
            "top_n": 2,
        },
        headers=h,
    ).json()
    assert ranked["results"][0]["index"] == 1
    chat = s.gateway.post(
        "/v1/chat",
        json={
            "profile": "dev-offline",
            "messages": [{"role": "user", "content": PROMPT}],
            "classification": "restricted",
        },
        headers=h,
    ).json()
    assert chat["content"] == "Backups are kept for 35 days. [1]"
    assert chat["route"]["redacted"] is False  # on-prem: data never leaves
    assert chat["cost_usd"] == "0"
    assert s.providers.requests == []  # no network at all
