"""Cross-service: identity outbox -> relay -> bus -> audit hash chain (EV-01 + AU-01)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from nexiqon_audit.main import create_app as audit_app
from nexiqon_audit.settings import ServiceSettings as AuditSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.bus import InMemoryBus
from nexiqon_core.db import create_engine
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, EventSettings
from nexiqon_core.signing import SigningSettings
from nexiqon_core.tenancy import CONTEXT_HEADER
from nexiqon_core.testing import make_keypair
from nexiqon_identity.main import create_app as identity_app
from nexiqon_identity.settings import IdpProviderSettings
from nexiqon_identity.settings import ServiceSettings as IdentitySettings
from nexiqon_identity.testing import OIDC_ISSUER, FakeIdp

pytestmark = pytest.mark.integration
ROLES = {"owner": ["**"], "member": ["identity.*.read"]}


@dataclass
class Stack:
    identity: httpx.AsyncClient
    audit: httpx.AsyncClient
    identity_app: Any
    audit_app: Any
    bus: InMemoryBus
    idp: FakeIdp
    owner_url: str

    async def signup(self, sub: str) -> tuple[str, str]:
        slug = f"a-{uuid.uuid4().hex[:8]}"
        token = self.idp.user(sub, f"{sub}@example.com")
        r = await self.identity.post(
            "/v1/session/tenants",
            json={"name": "Audit Co", "slug": slug},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201, r.text
        ctx = await self.identity.post(
            "/internal/ext-authz/x",
            headers={"Authorization": f"Bearer {token}", "X-Nexiqon-Tenant": slug},
        )
        return slug, ctx.headers[CONTEXT_HEADER]

    async def flush(self) -> None:
        await self.identity_app.state.events.relay_once()


@pytest.fixture(scope="session")
def migrated(postgres: PgUrls) -> PgUrls:
    upgrade("identity", postgres.owner, postgres.app_role)
    upgrade("audit", postgres.owner, postgres.app_role)
    return postgres


@pytest.fixture
async def stack(migrated: PgUrls) -> AsyncIterator[Stack]:
    postgres = migrated
    private, public = make_keypair()
    tokens = ContextTokenSettings(public_keys={"k": public})
    bus = InMemoryBus()
    idp = FakeIdp(OIDC_ISSUER)
    events = EventSettings(enabled=True)
    db = DatabaseSettings(url=postgres.app)

    async def fetch(_: str) -> dict[str, Any]:
        return idp.jwks()

    ident = identity_app(
        IdentitySettings(
            log_json=False,
            database=db,
            context_token=tokens,
            events=events,
            signing=SigningSettings(active_kid="k", private_keys={"k": private}),
            idp_providers=[
                IdpProviderSettings(
                    name="kc", kind="keycloak", issuer=OIDC_ISSUER, jwks_url="mem://"
                )
            ],
            context_cache_seconds=0,
        ),
        authorizer=StaticAuthorizer(ROLES),
        bus=bus,
        jwks_fetcher=fetch,
    )
    aud = audit_app(
        AuditSettings(log_json=False, database=db, context_token=tokens, events=events),
        authorizer=StaticAuthorizer(ROLES),
        bus=bus,
    )
    await aud.state.events.start()  # subscribes the recorder to the shared bus
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=ident), base_url="http://identity"
        ) as i,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=aud), base_url="http://audit") as a,
    ):
        yield Stack(i, a, ident, aud, bus, idp, postgres.owner)
    await aud.state.events.stop()
    await ident.state.db.engine.dispose()
    await aud.state.db.engine.dispose()


async def test_identity_events_land_in_a_verifiable_chain(stack: Stack) -> None:
    _, owner = await stack.signup("chain-owner")
    r = await stack.identity.post(
        "/v1/members", json={"email": "m@example.com"}, headers={CONTEXT_HEADER: owner}
    )
    assert r.status_code == 201
    await stack.flush()

    page = (await stack.audit.get("/v1/events", headers={CONTEXT_HEADER: owner})).json()
    assert [e["type"] for e in page["items"]] == [
        "nexiqon.identity.membership.invited",
        "nexiqon.identity.tenant.created",
    ]
    assert [e["seq"] for e in page["items"]] == [2, 1]
    filtered = (
        await stack.audit.get(
            "/v1/events?type=nexiqon.identity.tenant.*", headers={CONTEXT_HEADER: owner}
        )
    ).json()
    assert len(filtered["items"]) == 1
    one = (await stack.audit.get("/v1/events?limit=1", headers={CONTEXT_HEADER: owner})).json()
    assert one["next_before_seq"] == 2

    verify = (await stack.audit.get("/v1/verify", headers={CONTEXT_HEADER: owner})).json()
    assert verify["ok"] is True
    assert verify["length"] == 2


async def test_redelivery_is_idempotent(stack: Stack) -> None:
    _, owner = await stack.signup("idem-owner")
    await stack.flush()
    original = stack.bus.published[-1]
    recorder = stack.audit_app.state.events._subs[0].handler
    await recorder(original)  # a redelivery
    await recorder(original)
    items = (await stack.audit.get("/v1/events", headers={CONTEXT_HEADER: owner})).json()["items"]
    assert len(items) == 1


async def test_chain_is_append_only_and_tampering_is_detected(stack: Stack) -> None:
    _, owner = await stack.signup("tamper-owner")
    await stack.identity.post(
        "/v1/members", json={"email": "t@example.com"}, headers={CONTEXT_HEADER: owner}
    )
    await stack.flush()
    tenant_id = (await stack.identity.get("/v1/tenant", headers={CONTEXT_HEADER: owner})).json()[
        "id"
    ]

    engine = create_engine(stack.owner_url)
    try:
        with pytest.raises(Exception, match="append-only"):
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE audit.audit_events SET actor_id = 'x' WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
        # A privileged attacker who disables the trigger is still caught by the chain.
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE audit.audit_events DISABLE TRIGGER append_only"))
            await conn.execute(
                text(
                    "UPDATE audit.audit_events SET data = '{\"forged\": true}' WHERE tenant_id = :t AND seq = 1"
                ),
                {"t": tenant_id},
            )
            await conn.execute(text("ALTER TABLE audit.audit_events ENABLE TRIGGER append_only"))
    finally:
        await engine.dispose()
    verify = (await stack.audit.get("/v1/verify", headers={CONTEXT_HEADER: owner})).json()
    assert verify == {"ok": False, "length": 0, "head": "0" * 64, "first_broken_seq": 1}


async def test_audit_is_admin_only_and_tenant_isolated(stack: Stack) -> None:
    slug_a, owner_a = await stack.signup("iso-a")
    _, owner_b = await stack.signup("iso-b")
    await stack.identity.post(
        "/v1/members",
        json={"email": "mem@example.com", "role": "member"},
        headers={CONTEXT_HEADER: owner_a},
    )
    await stack.flush()
    member_token = stack.idp.user("mem", "mem@example.com")
    r = await stack.identity.post(
        "/internal/ext-authz/x",
        headers={"Authorization": f"Bearer {member_token}", "X-Nexiqon-Tenant": slug_a},
    )
    member = r.headers[CONTEXT_HEADER]
    assert (
        await stack.audit.get("/v1/events", headers={CONTEXT_HEADER: member})
    ).status_code == 403
    b_items = (await stack.audit.get("/v1/events", headers={CONTEXT_HEADER: owner_b})).json()[
        "items"
    ]
    assert {e["type"] for e in b_items} == {"nexiqon.identity.tenant.created"}
    assert all("iso-a" not in str(e["data"]) for e in b_items)
