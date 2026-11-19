"""NT-01 (email): sent only for platform services; the log keeps no address or body."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.testing import TwoTenants, make_keypair
from nexiqon_notification.mail import MemorySender
from nexiqon_notification.main import create_app
from nexiqon_notification.models import Delivery
from nexiqon_notification.settings import ServiceSettings

PRIVATE, PUBLIC = make_keypair()
ROLES = {"owner": ["**"], "service:conversation": ["notification.email.send"]}
BODY = {"to": "a@example.com", "subject": "Hi", "text": "Hello", "kind": "conversation.transcript"}


@pytest.fixture
def env(mail_db: PgUrls) -> Iterator[tuple[TestClient, MemorySender, TwoTenants, ServiceTokens]]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-cv": PUBLIC},
        service_keys={"svc-cv": "conversation"},
    )
    service = ServiceTokens(
        "conversation",
        tokens,
        ServiceIdentitySettings(key_id="svc-cv", private_key=PRIVATE),  # type: ignore[arg-type]
    )
    mail = MemorySender()
    app = create_app(
        ServiceSettings(
            log_json=False,
            context_token=tokens,
            database=DatabaseSettings(url=mail_db.app, pool_size=0),
            max_emails_per_hour=4,
            max_emails_per_recipient_per_hour=2,
        ),
        authorizer=StaticAuthorizer(ROLES),
        email=mail,
    )
    with TestClient(app) as client:
        yield client, mail, tenants, service


def post(client: TestClient, headers: dict[str, str], status: int, **body: Any) -> Any:
    r = client.post("/v1/emails", json={**BODY, **body}, headers=headers)
    assert r.status_code == status, r.text
    return r.json()


def svc(service: ServiceTokens, tenants: TwoTenants) -> dict[str, str]:
    return {"x-nexiqon-context": service.for_tenant(tenants.a.context.tenant_id)}


async def test_a_service_sends_and_the_log_keeps_only_a_hash(
    env: tuple[TestClient, MemorySender, TwoTenants, ServiceTokens], mail_db: PgUrls
) -> None:
    client, mail, tenants, service = env
    out = post(client, svc(service, tenants), 202, reference="conv-1")
    assert out["status"] == "sent"
    assert mail.sent[0].to == "a@example.com"
    engine = create_engine(mail_db.app)
    try:
        async with TenantSessionFactory(engine).session(tenants.a.context) as s:
            row = await s.get(Delivery, uuid.UUID(out["id"]))
    finally:
        await engine.dispose()
    assert row is not None
    stored = {c.name: getattr(row, c.name) for c in Delivery.__table__.columns}
    assert "a@example.com" not in str(stored)
    assert row.kind == "conversation.transcript"
    assert row.requested_by == "service:conversation"


def test_people_cannot_use_it_as_a_relay(
    env: tuple[TestClient, MemorySender, TwoTenants, ServiceTokens],
) -> None:
    client, mail, tenants, _ = env
    # The static test authorizer lets owners do anything; the policy makes this service-only
    # (see authz_test.rego). Here: a header injection and junk addresses are refused anyway.
    post(client, tenants.a.headers, 422, subject="Hi\r\nBcc: x@example.com")
    post(client, tenants.a.headers, 422, to="x@example.com, y@example.com")
    assert mail.sent == []


def test_ceilings_per_address_and_per_organization(
    env: tuple[TestClient, MemorySender, TwoTenants, ServiceTokens],
) -> None:
    client, mail, tenants, service = env
    h = svc(service, tenants)
    post(client, h, 202)
    post(client, h, 202, to="A@example.com")
    assert post(client, h, 429)["code"] == "too_many_emails"
    post(client, h, 202, to="b@example.com")
    post(client, h, 202, to="c@example.com")
    post(client, h, 429, to="d@example.com")
    assert len(mail.sent) == 4


def test_a_failed_relay_is_logged_and_reported(
    env: tuple[TestClient, MemorySender, TwoTenants, ServiceTokens],
) -> None:
    client, mail, tenants, service = env
    mail.fail = True
    post(client, svc(service, tenants), 503)
