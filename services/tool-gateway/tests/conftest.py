"""tool-gateway fixtures: real config (tools, pack, agent) and Postgres; demo APIs as egress target."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.fetch import FetchPolicy
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair
from nexiqon_tool_gateway.main import create_app
from nexiqon_tool_gateway.mock_apis import app as mock_app
from nexiqon_tool_gateway.secrets import MemorySecrets
from nexiqon_tool_gateway.settings import ServiceSettings

PACK = (
    Path(__file__).resolve().parents[3] / "packs/saas-knowledge-assistant/pack.yaml"
).read_text()
SVC_PRIVATE, SVC_PUBLIC = make_keypair()
API = "mock-apis.example"
API_IP = "93.184.216.34"
# Mirrors services/authz/policies for the actions used here (admin_only: tool.invoke.high).
ROLES = {
    "owner": ["**"],
    "admin": ["**"],
    "editor": [
        "**.read",
        "config.**",
        "tool.definitions.test",
        "tool.invoke.read",
        "tool.invoke.write",
        "tool.openapi.import",
        "tool.approvals.decide",
    ],
    "member": ["**.read", "tool.invoke.read", "tool.invoke.write"],
    "end_user": ["tool.definitions.read", "tool.invoke.read", "tool.invoke.write"],
    "service:tool-gateway": ["config.tool.read", "config.agent.read"],
}

ACCOUNT_TOOL: dict[str, Any] = {
    "description": "Look up the signed-in customer's account and plan",
    "kind": "rest",
    "risk_level": "read",
    "confirmation": "never",
    "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
    "request": {
        "method": "GET",
        "url_template": f"https://{API}/accounts/{{caller.actor_id}}",
        "host_allowlist": [API],
        "auth": {"scheme": "bearer"},
    },
    "credential_ref": "secret://demo-crm",
    "output_schema": {
        "type": "object",
        "properties": {"account_id": {}, "plan": {}, "status": {}, "renews_on": {}},
    },
    "result_classification": "confidential",
}
CASE_TOOL: dict[str, Any] = {
    "description": "Open a support case for the customer",
    "kind": "rest",
    "risk_level": "write",
    "confirmation": "always",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["subject"],
        "properties": {
            "subject": {"type": "string", "minLength": 3, "maxLength": 200},
            "description": {"type": "string", "maxLength": 4000},
        },
    },
    "request": {
        "method": "POST",
        "url_template": f"https://{API}/cases",
        "host_allowlist": [API],
        "auth": {"scheme": "bearer"},
    },
    "credential_ref": "secret://demo-crm",
}
CASE_STATUS_TOOL: dict[str, Any] = {
    "description": "Check the status of a support case",
    "kind": "rest",
    "risk_level": "read",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["case_id"],
        "properties": {"case_id": {"type": "string", "maxLength": 200}},
    },
    "request": {
        "method": "GET",
        "url_template": f"https://{API}/cases/{{case_id}}",
        "host_allowlist": [API],
        "auth": {"scheme": "bearer"},
    },
    "credential_ref": "secret://demo-crm",
}


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


@pytest.fixture(scope="session")
def tool_db(postgres: PgUrls) -> PgUrls:
    upgrade("config", postgres.owner, postgres.app_role)
    upgrade("tool-gateway", postgres.owner, postgres.app_role)
    return postgres


@dataclass
class Upstream:
    """The demo APIs behind a recording transport (what actually left the gateway)."""

    requests: list[httpx.Request] = field(default_factory=list)
    fail_with: int | None = None
    dns: dict[str, list[str]] = field(
        default_factory=lambda: {API: [API_IP], "internal.example": ["10.1.2.3"]}
    )

    def transport(self) -> httpx.AsyncBaseTransport:
        inner = httpx.ASGITransport(app=mock_app)
        outer = self

        class Recording(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                outer.requests.append(request)
                if outer.fail_with:
                    return httpx.Response(outer.fail_with, json={"detail": "upstream down"})
                return await inner.handle_async_request(request)

        return Recording()

    async def resolve(self, host: str, port: int) -> list[str]:
        return self.dns.get(host, [host])


@dataclass
class Stack:
    client: TestClient
    config: TestClient
    tenants: TwoTenants
    upstream: Upstream
    secrets: MemorySecrets
    db_url: str

    def headers(
        self,
        roles: set[str] | None = None,
        actor: str = "cust-42",
        actor_type: str = "user",
        tenant: str = "a",
    ) -> dict[str, str]:
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        ctx = TenantContext(
            t, actor, actor_type, frozenset({"end_user"} if roles is None else roles)
        )  # type: ignore[arg-type]
        return {CONTEXT_HEADER: self.tenants.issuer.issue(ctx)}

    def deploy(self, kind: str, name: str, spec: Any, tenant: str = "a") -> None:
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

    def invoke(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        agent: str = "support",
        key: str | None = None,
        approval: str | None = None,
        status: int = 200,
    ) -> Any:
        body: dict[str, Any] = {"agent": agent, "arguments": arguments or {}}
        if key:
            body["idempotency_key"] = key
        if approval:
            body["approval_id"] = approval
        return ok(
            self.client.post(
                f"/v1/tools/{tool}/invoke", json=body, headers=headers or self.headers()
            ),
            status,
        )


def build(
    tool_db: PgUrls,
    tenants: TwoTenants,
    upstream: Upstream,
    secrets: MemorySecrets,
    **overrides: Any,
) -> tuple[TestClient, TestClient]:
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-tg": SVC_PUBLIC},
        service_keys={"svc-tg": "tool-gateway"},
    )
    authorizer = StaticAuthorizer(ROLES)
    db = DatabaseSettings(url=tool_db.app, pool_size=0)
    config_settings = ConfigSettings(log_json=False, context_token=tokens, database=db)
    setup = TestClient(create_config_app(config_settings, authorizer=authorizer))
    config_for_gateway = create_config_app(config_settings, authorizer=authorizer)
    settings = ServiceSettings(
        log_json=False,
        context_token=tokens,
        database=db,
        service_identity=ServiceIdentitySettings(key_id="svc-tg", private_key=SVC_PRIVATE),  # type: ignore[arg-type]
        config_url="http://config",
        definition_cache_seconds=0,
        egress=FetchPolicy(),
        **overrides,
    )
    app = create_app(
        settings,
        authorizer=authorizer,
        secrets=secrets,
        config_transport=httpx.ASGITransport(app=config_for_gateway),
        egress_transport=upstream.transport(),
        egress_resolver=upstream.resolve,
    )
    return TestClient(app), setup


@pytest.fixture
def stack(tool_db: PgUrls) -> Iterator[Stack]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    upstream = Upstream()
    secrets = MemorySecrets()
    client, config = build(tool_db, tenants, upstream, secrets)
    with client, config:
        s = Stack(client, config, tenants, upstream, secrets, tool_db.app)
        s.deploy("domain_pack", "saas-knowledge-assistant", PACK)
        for name, spec in (
            ("account-lookup", ACCOUNT_TOOL),
            ("open-case", CASE_TOOL),
            ("case-status", CASE_STATUS_TOOL),
        ):
            s.deploy("tool", name, spec)
        s.deploy(
            "agent",
            "support",
            {
                "pack": {"name": "saas-knowledge-assistant"},
                "display_name": "Help",
                "tools": ["account-lookup", "open-case", "case-status"],
            },
        )
        ok(
            client.put(
                "/v1/credentials/demo-crm",
                json={"value": "demo-token-acme"},
                headers=s.headers({"admin"}, actor="admin-1"),
            ),
            204,
        )
        yield s
