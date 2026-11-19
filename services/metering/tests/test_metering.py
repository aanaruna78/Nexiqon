"""MT-01/MT-02: usage that matches the gateway, budgets and alerts, quality, KPIs, content gaps."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
from fastapi.testclient import TestClient

from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.events import OutboxRelay
from nexiqon_core.settings import DatabaseSettings
from nexiqon_metering.gaps import cluster
from nexiqon_model_gateway.main import create_app as create_gateway_app
from nexiqon_model_gateway.models import Outbox as GatewayOutbox
from nexiqon_model_gateway.settings import ServiceSettings as GatewaySettings

from .conftest import ROLES, Stack


class Collect:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def usage(stack: Stack, agent: str, cost: str, tokens: int = 100, **extra: Any) -> dict[str, Any]:
    return stack.event(
        "model-gateway.usage.recorded",
        {
            "operation": "chat",
            "profile": "cloud-frontier",
            "provider": "openai",
            "model": "gpt-test",
            "agent": agent,
            "input_tokens": tokens,
            "output_tokens": tokens // 2,
            "cost_usd": cost,
            **extra,
        },
    )


async def test_usage_matches_the_gateways_own_accounting(stack: Stack) -> None:
    """MT-01 acceptance: metering's totals equal model-gateway's usage report."""
    h = stack.tenants.a.headers
    db = DatabaseSettings(url=stack.db.app, pool_size=0)
    config = create_config_app(
        ConfigSettings(log_json=False, context_token=stack.tenants.settings, database=db),
        authorizer=StaticAuthorizer(ROLES),
    )
    gateway_app = create_gateway_app(
        GatewaySettings(
            log_json=False,
            context_token=stack.tenants.settings,
            database=db,
            config_url="http://config",
            allow_offline_provider=True,
            profile_cache_seconds=0,
        ),
        authorizer=StaticAuthorizer(ROLES),
        config_transport=httpx.ASGITransport(app=config),
    )
    with TestClient(gateway_app) as gateway:
        for agent in ("helper", "helper", "billing"):
            r = gateway.post(
                "/v1/chat",
                json={
                    "profile": "dev-offline",
                    "agent": agent,
                    "messages": [{"role": "user", "content": "How do backups work?"}],
                },
                headers=h,
            )
            assert r.status_code == 200, r.text
        r = gateway.post(
            "/v1/embeddings", json={"profile": "dev-offline", "inputs": ["a b", "c"]}, headers=h
        )
        assert r.status_code == 200, r.text
        report = gateway.get("/v1/usage", headers=h).json()
    engine = create_engine(stack.db.app)
    collect = Collect()
    try:
        async with TenantSessionFactory(engine).system_session() as s:
            while await OutboxRelay(collect, GatewayOutbox).relay_once(s):
                pass
    finally:
        await engine.dispose()
    mine = [
        e for e in collect.events if e["nexiqontenantid"] == str(stack.tenants.a.context.tenant_id)
    ]
    await stack.feed(*mine)
    summary = stack.get("/v1/usage/summary")
    want_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in report["rows"])
    assert summary["input_tokens"] + summary["output_tokens"] == want_tokens > 0
    assert Decimal(summary["cost_usd"]) == Decimal(report["total_cost_usd"])
    assert summary["calls"] == sum(r["calls"] for r in report["rows"]) == 4
    by_agent = {g["key"]: g["calls"] for g in summary["by_agent"]}
    assert by_agent == {"helper": 2, "billing": 1, "": 1}  # embeddings are not an assistant's


async def test_a_redelivered_event_counts_once(stack: Stack) -> None:
    e = usage(stack, "helper", "0.50")
    await stack.feed(e, e, dict(e))
    assert stack.get("/v1/usage/summary")["calls"] == 1


async def test_budgets_alert_once_per_threshold_and_admins_set_them(stack: Stack) -> None:
    r = stack.client.put("/v1/budgets", json={"monthly_usd": "10"}, headers=stack.headers("editor"))
    assert r.status_code == 403
    r = stack.client.put(
        "/v1/budgets",
        json={"monthly_usd": "10", "thresholds": [0.5, 1.0]},
        headers=stack.headers("admin"),
    )
    assert r.status_code == 200, r.text
    r = stack.client.put(
        "/v1/budgets", json={"agent": "helper", "monthly_usd": "2"}, headers=stack.headers("admin")
    )
    assert r.status_code == 200, r.text
    await stack.feed(usage(stack, "helper", "1.20"), usage(stack, "billing", "4.00"))
    alerts = stack.get("/v1/alerts")
    seen = sorted((a["agent"] or "", a["threshold"]) for a in alerts)
    # helper: 1.20 of 2 (50%); organization: 5.20 of 10 (50%).
    assert seen == [("", 0.5), ("helper", 0.5)]
    await stack.feed(usage(stack, "helper", "1.00"), usage(stack, "billing", "0.01"))
    seen = sorted((a["agent"] or "", a["threshold"]) for a in stack.get("/v1/alerts"))
    assert seen == [("", 0.5), ("helper", 0.5), ("helper", 0.8), ("helper", 1.0)]
    budgets = {b["agent"]: b for b in stack.get("/v1/budgets")}
    assert budgets["helper"]["spent_usd"] == "2.200000"
    assert budgets["helper"]["used"] == 1.1
    first = stack.get("/v1/alerts")[0]
    r = stack.client.post(f"/v1/alerts/{first['id']}/acknowledge", headers=stack.headers("admin"))
    assert r.json()["acknowledged_at"]
    assert len(stack.get("/v1/alerts", params={"open_only": True})) == 3


async def conversation(
    stack: Stack, cid: str, *, answered: bool, escalate: bool = False, down: bool = False
) -> None:
    base = {"conversation_id": cid, "agent": "helper", "channel": "widget"}
    events = [
        stack.event("conversation.started", base),
        stack.event(
            "conversation.turn.completed",
            {**base, "abstained": not answered, "citations": int(answered)},
        ),
    ]
    if escalate:
        events.append(stack.event("conversation.escalated", base))
    if down:
        events.append(
            stack.event(
                "conversation.feedback.given", {**base, "rating": "down", "message_id": "m"}
            )
        )
    await stack.feed(*events)


async def test_quality_rates_and_the_packs_kpis(stack: Stack) -> None:
    await conversation(stack, "c1", answered=True)
    await conversation(stack, "c2", answered=True, down=True)
    await conversation(stack, "c3", answered=False, escalate=True)
    await conversation(stack, "c4", answered=True)
    await stack.feed(
        stack.event(
            "conversation.feedback.given",
            {"rating": "up", "agent": "helper", "conversation_id": "c1"},
        )
    )
    await stack.feed(stack.event("tool-gateway.call.completed", {"agent": "helper", "ok": False}))
    q = stack.get("/v1/insights/quality", params={"agent": "helper"})
    assert q["totals"]["conversations"] == 4
    assert q["totals"]["turns"] == 4
    assert q["rates"]["answer_rate"] == 0.75
    assert q["rates"]["escalation_rate"] == 0.25
    assert q["rates"]["satisfaction"] == 0.5
    assert q["rates"]["tool_error_rate"] == 1.0
    assert q["previous_rates"]["answer_rate"] is None
    kpis = {k["name"]: k for k in stack.get("/v1/insights/kpis", params={"agent": "helper"})}
    assert kpis["deflection_rate"]["value"] == 0.75  # answered and never handed over
    assert kpis["handoff_rate"]["value"] == 0.25
    assert set(stack.peers.seen) == {"service:metering"}  # metering asks as itself


def q(text: str, reason: str = "unanswered") -> dict[str, str]:
    return {"question": text, "reason": reason, "conversation_id": "c"}


def test_content_gaps_group_questions_by_topic() -> None:
    topics = cluster(
        [
            q("How long are nightly backups kept?"),
            q("Are nightly backups kept for a year?", "escalated"),
            q("nightly backups kept how long"),
            q("Is there an SSO integration with Okta?"),
            q("Does SSO work with Okta?", "not_helpful"),
            q("What is the CEO's home address?"),
        ]
    )
    assert topics[0]["count"] == 3
    assert "backups" in topics[0]["label"]
    assert topics[0]["reasons"] == {"unanswered": 2, "escalated": 1}
    assert topics[1]["count"] == 2
    assert "okta" in topics[1]["label"]
    assert sum(t["count"] for t in topics) == 6
    assert cluster([]) == []


def test_gap_report_needs_more_than_read_access(stack: Stack) -> None:
    stack.peers.gap_questions = [
        {
            "question": "How long are nightly backups kept?",
            "reason": "unanswered",
            "conversation_id": "c1",
        },
        {
            "question": "nightly backups kept for how long",
            "reason": "escalated",
            "conversation_id": "c2",
        },
    ]
    stack.get("/v1/insights/gaps", 403, headers=stack.headers("member"))
    report = stack.get(
        "/v1/insights/gaps", headers=stack.headers("editor"), params={"agent": "helper"}
    )
    assert report["questions"] == 2
    assert report["topics"][0]["count"] == 2


async def test_tenants_are_apart_and_deletion_leaves_nothing(stack: Stack) -> None:
    await stack.feed(usage(stack, "helper", "1.00"))
    await stack.feed(
        stack.event("model-gateway.usage.recorded", {"agent": "x", "cost_usd": "9"}, tenant="b")
    )
    assert stack.get("/v1/usage/summary")["cost_usd"] == "1.000000"
    assert (
        stack.get("/v1/usage/summary", headers=stack.headers(tenant="b"))["cost_usd"] == "9.000000"
    )
    report = await stack.app.state.lifecycle.delete_tenant(stack.tenants.a.context.tenant_id)
    assert report.residue_check_passed
    assert stack.get("/v1/usage/summary")["calls"] == 0
