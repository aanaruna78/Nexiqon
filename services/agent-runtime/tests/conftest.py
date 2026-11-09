"""agent-runtime fixtures: real config (with the real SaaS Knowledge Assistant pack) and Postgres;
fake model gateway, retrieval and ingestion."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_agent_runtime.main import create_app
from nexiqon_agent_runtime.settings import ServiceSettings
from nexiqon_agent_runtime.testing import FakeServices, HostRouter
from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair

ROOT = Path(__file__).resolve().parents[3]
PACK = (ROOT / "packs/saas-knowledge-assistant/pack.yaml").read_text()
ROLES = {
    "owner": ["**"],
    "member": ["**.read", "agent.query.run", "model.inference.run", "config.profiles.resolve"],
    "end_user": ["agent.query.run"],
    "service:agent-runtime": ["config.agent.read", "ingestion.collections.read"],
}
SVC_PRIVATE, SVC_PUBLIC = make_keypair()
AGENT = {
    "pack": {"name": "saas-knowledge-assistant"},
    "display_name": "Acme Help",
    "knowledge": {"collections": ["product-docs"]},
    "behaviour": {"tone": "friendly", "product_name": "Acme"},
}


@pytest.fixture(scope="session")
def agent_db(postgres: PgUrls) -> PgUrls:
    upgrade("config", postgres.owner, postgres.app_role)
    upgrade("agent-runtime", postgres.owner, postgres.app_role)
    return postgres


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


@dataclass
class Stack:
    client: TestClient
    config: TestClient
    tenants: TwoTenants
    fakes: FakeServices
    db_url: str
    tokens: ContextTokenSettings

    def headers(
        self,
        roles: set[str] | None = None,
        actor: str = "user-a",
        tenant: str = "a",
        actor_type: str = "user",
    ) -> dict[str, str]:
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        ctx = TenantContext(t, actor, actor_type, frozenset(roles or {"member"}))  # type: ignore[arg-type]
        return {CONTEXT_HEADER: self.tenants.issuer.issue(ctx)}

    def deploy(self, kind: str, name: str, spec: dict[str, Any] | str, tenant: str = "a") -> None:
        h = (self.tenants.a if tenant == "a" else self.tenants.b).headers
        if kind == "domain_pack":
            ok(
                self.config.post(
                    "/v1/packs/import",
                    content=str(spec),
                    headers={**h, "content-type": "application/yaml"},
                ),
                201,
            )
        else:
            ok(
                self.config.post(
                    "/v1/objects", json={"kind": kind, "name": name, "spec": spec}, headers=h
                ),
                201,
            )
        ok(self.config.post(f"/v1/objects/{kind}/{name}/versions/1/publish", headers=h))
        ok(
            self.config.put(
                f"/v1/objects/{kind}/{name}/deployments/dev", json={"version": 1}, headers=h
            )
        )

    def run(
        self,
        thread: str,
        text: str | None = None,
        *,
        resume: Any = None,
        headers: dict[str, str] | None = None,
        agent: str = "support",
        status: int = 200,
    ) -> Any:
        body: dict[str, Any] = {"thread_id": thread}
        if text is not None:
            body["input"] = text
        if resume is not None:
            body["resume"] = resume
        return ok(
            self.client.post(
                f"/v1/agents/{agent}/runs", json=body, headers=headers or self.headers()
            ),
            status,
        )


def build(
    agent_db: PgUrls, tenants: TwoTenants, fakes: FakeServices, **overrides: Any
) -> tuple[TestClient, TestClient, ContextTokenSettings]:
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-ar": SVC_PUBLIC},
        service_keys={"svc-ar": "agent-runtime"},
    )
    authorizer = StaticAuthorizer(ROLES)
    db = DatabaseSettings(url=agent_db.app)
    # Separate config apps for setup and for agent-runtime's in-process calls (separate loops).
    config_app = create_config_app(
        ConfigSettings(log_json=False, context_token=tokens, database=db), authorizer=authorizer
    )
    config_for_runtime = create_config_app(
        ConfigSettings(log_json=False, context_token=tokens, database=db), authorizer=authorizer
    )
    router = HostRouter(
        {"config": httpx.ASGITransport(app=config_for_runtime)}, httpx.MockTransport(fakes)
    )
    settings = ServiceSettings(
        log_json=False,
        context_token=tokens,
        database=db,
        service_identity=ServiceIdentitySettings(key_id="svc-ar", private_key=SVC_PRIVATE),  # type: ignore[arg-type]
        config_url="http://config",
        ingestion_url="http://ingestion",
        retrieval_url="http://retrieval",
        model_gateway_url="http://model-gateway",
        agent_cache_seconds=0,
        **overrides,
    )
    return (
        TestClient(create_app(settings, authorizer=authorizer, service_transport=router)),
        TestClient(config_app),
        tokens,
    )


@pytest.fixture
def stack(agent_db: PgUrls) -> Iterator[Stack]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    fakes = FakeServices()
    client, config, tokens = build(agent_db, tenants, fakes)
    with client, config:
        s = Stack(client, config, tenants, fakes, agent_db.app, tokens)
        s.deploy("domain_pack", "saas-knowledge-assistant", PACK)
        s.deploy("agent", "support", AGENT)
        yield s
