"""NT-01: signed webhooks with retries and SSRF protection, and the in-app inbox by role."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import DatabaseSettings
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_core.testing import TwoTenants
from nexiqon_notification.dispatch import inbox_item, matches, sign
from nexiqon_notification.main import create_app
from nexiqon_notification.models import WebhookDelivery
from nexiqon_notification.settings import ServiceSettings

ROLES = {"owner": ["**"], "admin": ["**"], "editor": ["**.read"], "member": ["**.read"]}
HOOK = "https://hooks.example.com/nexiqon"


@dataclass
class Receiver:
    """The customer's endpoint: records what arrived; answers ``status``."""

    status: int = 200
    got: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.got.append(request)
        return httpx.Response(self.status)

    async def resolve(self, host: str, port: int) -> list[str]:
        return {"hooks.example.com": ["93.184.216.34"], "internal.example.com": ["10.0.0.5"]}[host]


@dataclass
class Env:
    client: TestClient
    tenants: TwoTenants
    receiver: Receiver
    app: Any
    db: PgUrls

    def headers(self, *roles: str) -> dict[str, str]:
        actor = f"user-{'-'.join(sorted(roles)) or 'admin'}"  # one person per role here
        ctx = TenantContext(
            self.tenants.a.context.tenant_id, actor, "user", frozenset(roles or {"admin"})
        )
        return {CONTEXT_HEADER: self.tenants.issuer.issue(ctx)}

    def event(self, kind: str, **data: Any) -> dict[str, Any]:
        return {
            "specversion": "1.0",
            "id": str(uuid.uuid4()),
            "type": f"nexiqon.{kind}",
            "source": "test",
            "time": datetime.now(UTC).isoformat(),
            "nexiqontenantid": str(self.tenants.a.context.tenant_id),
            "data": data,
        }


@pytest.fixture
def env(mail_db: PgUrls) -> Iterator[Env]:
    from nexiqon_core.migrations import upgrade

    upgrade("notification", mail_db.owner, mail_db.app_role)
    tenants = TwoTenants.create(roles=frozenset({"admin"}))
    receiver = Receiver()
    app = create_app(
        ServiceSettings(
            log_json=False,
            context_token=tenants.settings,
            database=DatabaseSettings(url=mail_db.app, pool_size=0),
            webhook_retry_seconds=0,
        ),
        authorizer=StaticAuthorizer(ROLES),
        webhook_transport=httpx.MockTransport(receiver),
        webhook_resolver=receiver.resolve,
    )
    with TestClient(app) as client:
        yield Env(client, tenants, receiver, app, mail_db)


def ok(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


def test_event_patterns() -> None:
    assert matches([], "nexiqon.anything.at.all")
    assert matches(["evaluation.*"], "nexiqon.evaluation.run.completed")
    assert matches(["conversation.escalated"], "nexiqon.conversation.escalated")
    assert not matches(["conversation.escalated"], "nexiqon.conversation.started")
    assert inbox_item({"type": "nexiqon.conversation.turn.completed", "data": {}}) is None


async def test_matching_events_arrive_signed_and_only_once(env: Env) -> None:
    created = ok(
        env.client.post(
            "/v1/webhooks", json={"url": HOOK, "events": ["conversation.*"]}, headers=env.headers()
        ),
        201,
    )
    secret = created["secret"]
    assert secret.startswith("whsec_")
    assert "secret" not in ok(env.client.get("/v1/webhooks", headers=env.headers()))[0]
    escalated = env.event("conversation.escalated", conversation_id="c1", agent="helper")
    await env.app.state.dispatcher(escalated)
    await env.app.state.dispatcher(escalated)  # redelivered: still one delivery
    await env.app.state.dispatcher(env.event("metering.budget.threshold_reached", threshold=0.8))
    assert len(env.receiver.got) == 1
    request = env.receiver.got[0]
    body = request.content
    t, v1 = (p.split("=", 1)[1] for p in request.headers["x-nexiqon-signature"].split(","))
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(v1, expected)
    assert json.loads(body)["type"] == "nexiqon.conversation.escalated"
    assert request.headers["x-nexiqon-event"] == "nexiqon.conversation.escalated"
    rows = ok(env.client.get(f"/v1/webhooks/{created['id']}/deliveries", headers=env.headers()))
    assert [(r["status"], r["attempts"]) for r in rows] == [("delivered", 1)]
    assert sign("s", b"x", at=1) == sign("s", b"x", at=1)


async def test_failures_retry_with_backoff_then_give_up(env: Env) -> None:
    created = ok(env.client.post("/v1/webhooks", json={"url": HOOK}, headers=env.headers()), 201)
    env.receiver.status = 503
    await env.app.state.dispatcher(env.event("evaluation.run.completed", agent="a"))
    [row] = ok(env.client.get(f"/v1/webhooks/{created['id']}/deliveries", headers=env.headers()))
    assert (row["status"], row["attempts"], row["response_status"]) == ("pending", 1, 503)
    assert datetime.fromisoformat(row["next_attempt_at"]) > datetime.now(UTC) + timedelta(
        seconds=20
    )
    engine = create_engine(env.db.app)
    try:
        for _ in range(5):  # make each retry due, then run the retry loop once
            async with TenantSessionFactory(engine).scoped(
                {"tenant_id": str(env.tenants.a.context.tenant_id)}
            ) as s:
                await s.execute(update(WebhookDelivery).values(next_attempt_at=datetime.now(UTC)))
            await env.app.state.dispatcher.send_due()
    finally:
        await engine.dispose()
    [row] = ok(env.client.get(f"/v1/webhooks/{created['id']}/deliveries", headers=env.headers()))
    assert (row["status"], row["attempts"]) == ("failed", 6)
    env.receiver.status = 200
    test = ok(env.client.post(f"/v1/webhooks/{created['id']}/test", headers=env.headers()))
    assert test["status"] == "delivered"


def test_webhooks_cannot_reach_internal_or_plain_http_addresses(env: Env) -> None:
    for url in ("https://internal.example.com/x", "http://hooks.example.com/x"):
        r = env.client.post("/v1/webhooks", json={"url": url}, headers=env.headers())
        assert r.status_code == 400, (url, r.text)


async def test_the_inbox_shows_each_role_what_it_acts_on(env: Env) -> None:
    await env.app.state.dispatcher(
        env.event(
            "metering.budget.threshold_reached",
            agent=None,
            threshold=0.8,
            spent_usd="80",
            limit_usd="100",
        )
    )
    await env.app.state.dispatcher(
        env.event("conversation.escalated", conversation_id="c9", agent="helper")
    )
    admin = ok(env.client.get("/v1/inbox", headers=env.headers("admin")))
    assert {i["kind"] for i in admin["items"]} == {"budget", "handover"}
    member = ok(env.client.get("/v1/inbox", headers=env.headers("member")))
    assert [i["kind"] for i in member["items"]] == ["handover"]
    assert member["items"][0]["link"] == "/conversations?c=c9"
    assert member["unread"] == 1
    after = ok(env.client.post("/v1/inbox/read", json={}, headers=env.headers("member")))
    assert after["unread"] == 0
    assert (
        ok(env.client.get("/v1/inbox", headers=env.headers("admin")))["unread"] == 2
    )  # per person
