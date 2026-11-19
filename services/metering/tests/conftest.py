"""metering fixtures: Postgres, the real model gateway (offline provider) and config for the
accounting check, and scripted config/conversation peers for KPIs and content gaps."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, ContextTokenVerifier, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair
from nexiqon_metering.main import create_app
from nexiqon_metering.settings import ServiceSettings

PRIVATE, PUBLIC = make_keypair()
ROLES = {
    "owner": ["**"],
    "admin": ["**"],
    "editor": ["**.read", "metering.gaps.view"],
    "member": ["**.read"],
    "end_user": ["model.inference.run", "config.profiles.resolve"],
}
PACK = {
    "analytics": {
        "kpis": [
            {
                "name": "deflection_rate",
                "description": "Resolved without a handoff",
                "event": "conversation.resolved",
            },
            {
                "name": "handoff_rate",
                "description": "Escalated to support",
                "event": "conversation.escalated",
            },
        ]
    }
}


@pytest.fixture(scope="session")
def metering_db(postgres: PgUrls) -> PgUrls:
    for service in ("config", "model-gateway", "metering"):
        upgrade(service, postgres.owner, postgres.app_role)
    return postgres


@dataclass
class Peers:
    """config and conversation as metering sees them; checks metering calls as itself."""

    verifier: ContextTokenVerifier
    gap_questions: list[dict[str, Any]] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        ctx = self.verifier.verify(request.headers[CONTEXT_HEADER])
        self.seen.append(ctx.actor_id)
        if request.url.host == "config":
            return httpx.Response(200, json={"agent": "helper", "config": {}, "pack": PACK})
        return httpx.Response(200, json=self.gap_questions)


@dataclass
class Stack:
    client: TestClient
    tenants: TwoTenants
    peers: Peers
    app: Any
    db: PgUrls

    def headers(self, *roles: str, tenant: str = "a") -> dict[str, str]:
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        ctx = TenantContext(t, "user-x", "user", frozenset(roles or {"owner"}))
        return {CONTEXT_HEADER: self.tenants.issuer.issue(ctx)}

    def get(self, url: str, status: int = 200, **kw: Any) -> Any:
        r = self.client.get(url, headers=kw.pop("headers", self.headers()), **kw)
        assert r.status_code == status, r.text
        return r.json()

    def event(
        self, kind: str, data: dict[str, Any], tenant: str = "a", event_id: str | None = None
    ) -> dict[str, Any]:
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        return {
            "id": event_id or str(uuid.uuid4()),
            "type": f"nexiqon.{kind}",
            "source": "test",
            "time": datetime.now(UTC).isoformat(),
            "nexiqontenantid": str(t),
            "nexiqonactorid": "user-x",
            "data": data,
        }

    async def feed(self, *events: dict[str, Any]) -> None:
        for e in events:
            await self.app.state.recorder(e)


@pytest.fixture
def stack(metering_db: PgUrls) -> Iterator[Stack]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-mt": PUBLIC},
        service_keys={"svc-mt": "metering"},
    )
    peers = Peers(ContextTokenVerifier(tokens))
    app = create_app(
        ServiceSettings(
            log_json=False,
            context_token=tokens,
            database=DatabaseSettings(url=metering_db.app, pool_size=0),
            metering_identity=ServiceIdentitySettings(key_id="svc-mt", private_key=PRIVATE),  # type: ignore[arg-type]
            config_url="http://config",
            conversation_url="http://conversation",
        ),
        authorizer=StaticAuthorizer(ROLES),
        service_transport=httpx.MockTransport(peers),
    )
    with TestClient(app) as client:
        yield Stack(client, tenants, peers, app, metering_db)
