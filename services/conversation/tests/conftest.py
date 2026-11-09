"""Conversation end to end: real conversation, agent-runtime and config services on Postgres;
fake model gateway, retrieval and ingestion."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_agent_runtime.main import create_app as create_runtime_app
from nexiqon_agent_runtime.settings import ServiceSettings as RuntimeSettings
from nexiqon_agent_runtime.testing import FakeServices, HostRouter
from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_conversation.main import create_app
from nexiqon_conversation.settings import ServiceSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair

PACK = (
    Path(__file__).resolve().parents[3] / "packs/saas-knowledge-assistant/pack.yaml"
).read_text()
STAFF = [
    "**.read",
    "conversation.**",
    "agent.query.run",
    "model.inference.run",
    "config.profiles.resolve",
]
ROLES = {
    "owner": ["**"],
    "member": STAFF,
    "end_user": [
        "agent.query.run",
        "conversation.messages.create",
        "conversation.own.read",
        "model.inference.run",
        "config.profiles.resolve",
    ],
    "service:agent-runtime": ["config.agent.read", "ingestion.collections.read"],
}
SVC_PRIVATE, SVC_PUBLIC = make_keypair()


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


@pytest.fixture(scope="session")
def conv_db(postgres: PgUrls) -> PgUrls:
    for service in ("config", "agent-runtime", "conversation"):
        upgrade(service, postgres.owner, postgres.app_role)
    return postgres


@dataclass
class Stack:
    client: TestClient
    tenants: TwoTenants
    fakes: FakeServices
    db_url: str

    def headers(
        self,
        roles: set[str] | None = None,
        actor: str = "user-a",
        actor_type: str = "user",
        tenant: str = "a",
    ) -> dict[str, str]:
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        ctx = TenantContext(t, actor, actor_type, frozenset(roles or {"end_user"}))  # type: ignore[arg-type]
        return {CONTEXT_HEADER: self.tenants.issuer.issue(ctx)}

    def start(
        self, headers: dict[str, str] | None = None, agent: str = "support"
    ) -> dict[str, Any]:
        out: dict[str, Any] = ok(
            self.client.post(
                "/v1/conversations",
                json={"agent": agent, "channel": "widget"},
                headers=headers or self.headers(),
            ),
            201,
        )
        return out

    def say(
        self, conversation: str, text: str, headers: dict[str, str] | None = None, status: int = 200
    ) -> Any:
        return ok(
            self.client.post(
                f"/v1/conversations/{conversation}/messages",
                json={"content": text},
                headers=headers or self.headers(),
            ),
            status,
        )


@pytest.fixture
def stack(conv_db: PgUrls) -> Iterator[Stack]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-ar": SVC_PUBLIC},
        service_keys={"svc-ar": "agent-runtime"},
    )
    authorizer = StaticAuthorizer(ROLES)
    db = DatabaseSettings(url=conv_db.app)
    config_settings = ConfigSettings(log_json=False, context_token=tokens, database=db)
    fakes = FakeServices()
    # Everything below runs inside the conversation client's event loop, except the setup client.
    setup = TestClient(create_config_app(config_settings, authorizer=authorizer))
    config_for_services = create_config_app(config_settings, authorizer=authorizer)
    runtime = create_runtime_app(
        RuntimeSettings(
            log_json=False,
            context_token=tokens,
            database=db,
            service_identity=ServiceIdentitySettings(key_id="svc-ar", private_key=SVC_PRIVATE),  # type: ignore[arg-type]
            config_url="http://config",
            ingestion_url="http://ingestion",
            retrieval_url="http://retrieval",
            model_gateway_url="http://model-gateway",
            agent_cache_seconds=0,
        ),
        authorizer=authorizer,
        service_transport=HostRouter(
            {"config": httpx.ASGITransport(app=config_for_services)}, httpx.MockTransport(fakes)
        ),
    )
    router = HostRouter(
        {
            "agent-runtime": httpx.ASGITransport(app=runtime),
            "config": httpx.ASGITransport(app=config_for_services),
        },
        httpx.MockTransport(fakes),
    )
    app = create_app(
        ServiceSettings(
            log_json=False,
            context_token=tokens,
            database=db,
            agent_runtime_url="http://agent-runtime",
            config_url="http://config",
            retention_sweep_seconds=0,
        ),
        authorizer=authorizer,
        service_transport=router,
    )
    h = tenants.a.headers
    with setup, TestClient(app) as client:
        ok(
            setup.post(
                "/v1/packs/import", content=PACK, headers={**h, "content-type": "application/yaml"}
            ),
            201,
        )
        for kind, name, spec in (
            ("domain_pack", "saas-knowledge-assistant", None),
            (
                "retention_profile",
                "short",
                {
                    "conversations_days": 30,
                    "traces_days": 7,
                    "tool_results_days": 7,
                    "legal_hold": False,
                },
            ),
            (
                "agent",
                "support",
                {
                    "pack": {"name": "saas-knowledge-assistant"},
                    "display_name": "Acme Help",
                    "knowledge": {"collections": ["product-docs"]},
                    "retention_profile": "short",
                },
            ),
        ):
            if spec is not None:
                ok(
                    setup.post(
                        "/v1/objects", json={"kind": kind, "name": name, "spec": spec}, headers=h
                    ),
                    201,
                )
            ok(setup.post(f"/v1/objects/{kind}/{name}/versions/1/publish", headers=h))
            ok(
                setup.put(
                    f"/v1/objects/{kind}/{name}/deployments/dev", json={"version": 1}, headers=h
                )
            )
        yield Stack(client, tenants, fakes, conv_db.app)
