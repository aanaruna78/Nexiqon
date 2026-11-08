"""Model gateway end to end: real config service and Postgres, fake provider network."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import select

from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.lifecycle import DeletionReport, ExportManifest
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_model_gateway.lifecycle import UsageLifecycle
from nexiqon_model_gateway.models import Outbox

from .conftest import StackFactory

pytestmark = pytest.mark.integration

OPENAI = "api.openai.com"
ANTHROPIC = "api.anthropic.com"
VLLM = "vllm"
USER = [{"role": "user", "content": "What is the retention period?"}]


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()


def cloud_profile(**extra: Any) -> dict[str, Any]:
    return {
        "chat": {"provider": "openai", "model": "gpt-4.1"},
        "embedding": {"provider": "openai", "model": "text-embedding-3-small", "dimensions": 1024},
        "data_policy": {"location": "cloud", "allow_training": False},
        **extra,
    }


def test_chat_uses_profile_records_usage_and_emits_event(make_stack: StackFactory) -> None:
    s = make_stack()
    h = s.tenants.a.headers
    out = ok(s.gateway.post("/v1/chat", json={"messages": USER}, headers=h))
    assert out["content"] == "You said: What is the retention period?"
    assert out["route"] == {
        "requested_profile": "cloud-frontier",
        "profile": "cloud-frontier",
        "routed": False,
        "fallback_used": False,
        "provider": "openai",
        "model": "gpt-4.1",
        "redacted": True,
    }
    assert out["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert float(out["cost_usd"]) > 0
    sent = s.providers.bodies(OPENAI)[0]
    assert sent["max_completion_tokens"] == 1200  # profile ceiling
    report = ok(s.gateway.get("/v1/usage", headers=h))
    assert report["rows"][0]["calls"] == 1
    assert report["rows"][0]["input_tokens"] == 100
    # Tenant B sees none of tenant A's usage.
    assert ok(s.gateway.get("/v1/usage", headers=s.tenants.b.headers))["rows"] == []

    async def events() -> list[str]:
        engine = create_engine(s.db_url)
        try:
            async with TenantSessionFactory(engine).system_session() as session:
                rows = await session.scalars(
                    select(Outbox.type).where(Outbox.tenant_id == s.tenants.a.context.tenant_id)
                )
                return list(rows)
        finally:
            await engine.dispose()

    assert asyncio.run(events()) == ["nexiqon.model-gateway.usage.recorded"]


def test_confidential_data_is_routed_on_prem_and_never_reaches_cloud(
    make_stack: StackFactory,
) -> None:
    s = make_stack()
    out = ok(
        s.gateway.post(
            "/v1/chat",
            json={"messages": USER, "classification": "confidential"},
            headers=s.tenants.a.headers,
        )
    )
    assert out["route"]["profile"] == "on-prem-standard"
    assert out["route"]["routed"] is True
    assert out["route"]["redacted"] is False  # on-prem: no redaction by default
    assert s.providers.hosts == [VLLM]
    assert float(out["cost_usd"]) == 0


def test_restricted_data_never_goes_to_a_cloud_profile(make_stack: StackFactory) -> None:
    s = make_stack()
    h = s.tenants.a.headers
    s.deploy_profile("cloud-only", cloud_profile(), h)
    r = s.gateway.post(
        "/v1/chat",
        json={"profile": "cloud-only", "messages": USER, "classification": "restricted"},
        headers=h,
    )
    assert r.status_code == 403
    assert s.providers.requests == []


def test_security_floor_blocks_forbidden_provider_before_any_call(
    make_stack: StackFactory,
) -> None:
    # Operator floor for an on-prem deployment: only self-hosted chat providers.
    s = make_stack(
        deployment_floors=[
            {"path": "model.chat.provider", "op": "subset_of", "value": ["openai_compatible"]}
        ]
    )
    r = s.gateway.post("/v1/chat", json={"messages": USER}, headers=s.tenants.a.headers)
    assert r.status_code == 409
    assert r.json()["code"] == "security_floor_violation"
    assert s.providers.requests == []
    on_prem = s.gateway.post(
        "/v1/chat",
        json={"profile": "on-prem-small", "messages": USER},
        headers=s.tenants.a.headers,
    )
    assert on_prem.status_code == 200
    assert s.providers.hosts == [VLLM]


def test_fallback_on_retryable_failure_only(make_stack: StackFactory) -> None:
    s = make_stack()
    h = s.tenants.a.headers
    s.providers.fail[OPENAI] = 503
    out = ok(s.gateway.post("/v1/chat", json={"messages": USER}, headers=h))
    assert out["route"]["profile"] == "cloud-frontier-backup"
    assert out["route"]["fallback_used"] is True
    assert out["route"]["provider"] == "anthropic"
    assert out["content"].startswith("Backup says:")
    assert s.providers.hosts == [OPENAI, ANTHROPIC]

    s.providers.requests.clear()
    s.providers.fail[OPENAI] = 400  # a bad request is not retried elsewhere
    r = s.gateway.post("/v1/chat", json={"messages": USER}, headers=h)
    assert r.status_code == 502
    assert r.json()["code"] == "provider_error"
    assert "provider says no" not in r.text  # upstream bodies are not echoed
    assert s.providers.hosts == [OPENAI]


def test_personal_data_is_redacted_for_cloud_and_restored(make_stack: StackFactory) -> None:
    s = make_stack()
    msg = [{"role": "user", "content": "Email jane@example.com about card 4111 1111 1111 1111"}]
    out = ok(s.gateway.post("/v1/chat", json={"messages": msg}, headers=s.tenants.a.headers))
    sent = s.providers.bodies(OPENAI)[0]["messages"][0]["content"]
    assert sent == "Email [EMAIL_1] about card [CARD_1]"
    assert out["content"] == "You said: Email jane@example.com about card 4111 1111 1111 1111"


def test_monthly_budget_is_enforced(make_stack: StackFactory) -> None:
    s = make_stack()
    h = s.tenants.a.headers
    s.deploy_profile("tight", cloud_profile(budgets={"monthly_usd": 0.0001}), h)
    ok(s.gateway.post("/v1/chat", json={"profile": "tight", "messages": USER}, headers=h))
    r = s.gateway.post("/v1/chat", json={"profile": "tight", "messages": USER}, headers=h)
    assert r.status_code == 429
    assert r.json()["code"] == "budget_exceeded"
    assert len(s.providers.requests) == 1


def test_conversation_token_budget(make_stack: StackFactory) -> None:
    s = make_stack()
    h = s.tenants.a.headers
    s.deploy_profile("convo", cloud_profile(budgets={"per_conversation_tokens": 1000}), h)
    body = {"profile": "convo", "messages": USER, "conversation_id": "c-1"}
    for _ in range(7):  # 150 tokens each
        ok(s.gateway.post("/v1/chat", json=body, headers=h))
    assert s.gateway.post("/v1/chat", json=body, headers=h).status_code == 429
    other = {**body, "conversation_id": "c-2"}
    ok(s.gateway.post("/v1/chat", json=other, headers=h))


def test_embeddings_keep_one_vector_space(make_stack: StackFactory) -> None:
    s = make_stack()
    h = s.tenants.a.headers
    out = ok(s.gateway.post("/v1/embeddings", json={"inputs": ["a", "b"]}, headers=h))
    assert out["dimensions"] == 1024
    assert len(out["vectors"]) == 2
    assert s.providers.bodies(OPENAI)[0]["dimensions"] == 1024
    # The profile routes confidential data elsewhere: refuse rather than mix embedding models.
    r = s.gateway.post(
        "/v1/embeddings", json={"inputs": ["a"], "classification": "confidential"}, headers=h
    )
    assert r.status_code == 403
    assert "on-prem-standard" in r.json()["detail"]
    on_prem = ok(
        s.gateway.post(
            "/v1/embeddings",
            json={"profile": "on-prem-standard", "inputs": ["q"], "input_type": "query"},
            headers=h,
        )
    )
    assert on_prem["route"]["model"] == "qwen3-embedding-0.6b"
    s.providers.dims = 768  # a misconfigured model
    bad = s.gateway.post("/v1/embeddings", json={"inputs": ["a"]}, headers=h)
    assert bad.status_code == 502


def test_rerank(make_stack: StackFactory) -> None:
    s = make_stack()
    h = s.tenants.a.headers
    docs = ["unrelated", "how retention works", "other"]
    r = s.gateway.post("/v1/rerank", json={"query": "retention", "documents": docs}, headers=h)
    assert r.status_code == 400  # cloud-frontier has no reranker
    out = ok(
        s.gateway.post(
            "/v1/rerank",
            json={
                "profile": "on-prem-standard",
                "query": "retention",
                "documents": docs,
                "top_n": 2,
            },
            headers=h,
        )
    )
    assert out["results"][0]["index"] == 1
    assert len(out["results"]) == 2


def test_permissions_and_widgets(make_stack: StackFactory) -> None:
    s = make_stack()
    tenant = s.tenants.a.context.tenant_id

    def token(roles: set[str], actor_type: str = "user") -> dict[str, str]:
        ctx = TenantContext(
            tenant_id=tenant,
            actor_id="x",
            actor_type=actor_type,
            roles=frozenset(roles),  # type: ignore[arg-type]
        )
        return {CONTEXT_HEADER: s.tenants.issuer.issue(ctx)}

    assert (
        s.gateway.post("/v1/chat", json={"messages": USER}, headers=token({"viewer"})).status_code
        == 403
    )
    widget = token({"end_user"}, "widget")
    assert s.gateway.post("/v1/chat", json={"messages": USER}, headers=widget).status_code == 200
    assert s.gateway.post("/v1/chat", json={"messages": USER}).status_code == 401
    assert s.providers.hosts == [OPENAI]


def test_unknown_profile_and_validation(make_stack: StackFactory) -> None:
    s = make_stack()
    h = s.tenants.a.headers
    assert (
        s.gateway.post(
            "/v1/chat", json={"profile": "nope", "messages": USER}, headers=h
        ).status_code
        == 404
    )
    assert s.gateway.post("/v1/chat", json={"messages": []}, headers=h).status_code == 422
    assert s.gateway.get("/v1/usage?month=2026-13", headers=h).status_code == 422
    assert s.providers.requests == []


def test_lifecycle_deletes_usage(make_stack: StackFactory) -> None:
    s = make_stack()
    ok(s.gateway.post("/v1/chat", json={"messages": USER}, headers=s.tenants.a.headers))
    tenant = s.tenants.a.context.tenant_id

    async def run() -> tuple[ExportManifest, DeletionReport]:
        engine = create_engine(s.db_url)
        try:
            lifecycle = UsageLifecycle("model-gateway", TenantSessionFactory(engine))
            return await lifecycle.export_tenant(tenant), await lifecycle.delete_tenant(tenant)
        finally:
            await engine.dispose()

    export, report = asyncio.run(run())
    assert export.artifacts[0]["rows"] == 1
    assert report.deleted == {"usage_records": 1, "outbox_events": 1}
    assert report.residue_check_passed
    assert ok(s.gateway.get("/v1/usage", headers=s.tenants.a.headers))["rows"] == []
