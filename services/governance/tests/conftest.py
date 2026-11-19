"""governance fixtures: Postgres, Temporal (time-skipping), and real services (identity, config,
conversation, evaluation, metering, notification) whose lifecycle endpoints the sagas call."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from temporalio.testing import WorkflowEnvironment

from nexiqon_authz.main import create_app as create_authz_app
from nexiqon_authz.settings import ServiceSettings as AuthzSettings
from nexiqon_channel.main import create_app as create_channel_app
from nexiqon_channel.settings import ServiceSettings as ChannelSettings
from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_conversation.main import create_app as create_conversation_app
from nexiqon_conversation.settings import ServiceSettings as ConversationSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.blobs import MemoryBlobStore
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair
from nexiqon_evaluation.main import create_app as create_evaluation_app
from nexiqon_evaluation.settings import ServiceSettings as EvaluationSettings
from nexiqon_governance.main import create_app
from nexiqon_governance.settings import ServiceSettings
from nexiqon_identity.main import create_app as create_identity_app
from nexiqon_identity.settings import ServiceSettings as IdentitySettings
from nexiqon_metering.main import create_app as create_metering_app
from nexiqon_metering.settings import ServiceSettings as MeteringSettings
from nexiqon_notification.main import create_app as create_notification_app
from nexiqon_notification.settings import ServiceSettings as NotificationSettings

PRIVATE, PUBLIC = make_keypair()
# Every kind of service: with tenant data (most), without a database (authz, channel), the
# organization itself (identity, last).
SERVICES = (
    "authz",
    "channel",
    "identity",
    "config",
    "conversation",
    "evaluation",
    "metering",
    "notification",
)
DB_SERVICES = ("identity", "config", "conversation", "evaluation", "metering", "notification")
ROLES = {
    "owner": ["**"],
    "admin": ["**"],
    "member": ["**.read"],
    "service:governance": ["governance.lifecycle.run", "config.profiles.resolve"],
}


@pytest.fixture(scope="session")
def gov_db(postgres: PgUrls) -> PgUrls:
    for service in (*DB_SERVICES, "governance"):
        upgrade(service, postgres.owner, postgres.app_role)
    return postgres


class Router(httpx.AsyncBaseTransport):
    def __init__(self, routes: dict[str, httpx.AsyncBaseTransport]) -> None:
        self.routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.routes[request.url.host].handle_async_request(request)


@dataclass
class Stack:
    tenants: TwoTenants
    api: httpx.AsyncClient
    clients: dict[str, httpx.AsyncClient]
    env: WorkflowEnvironment
    blobs: MemoryBlobStore
    apps: dict[str, Any]
    db: PgUrls

    def headers(self, *roles: str, tenant: str = "a") -> dict[str, str]:
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        ctx = TenantContext(t, "owner-1", "user", frozenset(roles or {"owner"}))
        return {CONTEXT_HEADER: self.tenants.issuer.issue(ctx)}

    async def ok(self, method: str, url: str, status: int = 200, **kw: Any) -> Any:
        r = await self.api.request(method, url, headers=kw.pop("headers", self.headers()), **kw)
        assert r.status_code == status, r.text
        return (
            r.json()
            if r.content and r.headers.get("content-type", "").startswith("application/json")
            else r
        )

    async def wait(self, kind: str, request_id: str) -> dict[str, Any]:
        tenant = self.tenants.a.context.tenant_id
        if kind == "delete":
            await self.env.sleep(3700)  # past the grace period (time-skipping)
        await self.env.client.get_workflow_handle(f"{tenant}:tenant-{kind}:{request_id}").result()
        out: dict[str, Any] = await self.ok("GET", f"/v1/lifecycle/requests/{request_id}")
        return out


@pytest.fixture
async def stack(gov_db: PgUrls) -> AsyncIterator[Stack]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-gov": PUBLIC},
        service_keys={"svc-gov": "governance"},
    )
    authorizer = StaticAuthorizer(ROLES)
    db = DatabaseSettings(url=gov_db.app, pool_size=0)
    common = {"log_json": False, "context_token": tokens, "database": db}
    apps: dict[str, Any] = {
        "authz": create_authz_app(AuthzSettings(log_json=False, context_token=tokens)),
        "channel": create_channel_app(
            ChannelSettings(log_json=False, context_token=tokens), authorizer=authorizer
        ),
        "identity": create_identity_app(IdentitySettings(**common), authorizer=authorizer),
        "config": create_config_app(ConfigSettings(**common), authorizer=authorizer),
        "conversation": create_conversation_app(
            ConversationSettings(**common, retention_sweep_seconds=0), authorizer=authorizer
        ),
        "evaluation": create_evaluation_app(EvaluationSettings(**common), authorizer=authorizer),
        "metering": create_metering_app(MeteringSettings(**common), authorizer=authorizer),
        "notification": create_notification_app(
            NotificationSettings(**common), authorizer=authorizer
        ),
    }
    routes: dict[str, httpx.AsyncBaseTransport] = {
        name: httpx.ASGITransport(app=app) for name, app in apps.items()
    }
    blobs = MemoryBlobStore()
    settings = ServiceSettings(
        **common,
        governance_identity=ServiceIdentitySettings(key_id="svc-gov", private_key=PRIVATE),  # type: ignore[arg-type]
        service_urls={name: f"http://{name}" for name in SERVICES},
        task_queue="governance-test",
        worker_max_cached_workflows=0,
        deletion_grace_hours=1.0,
    )
    async with AsyncExitStack() as stack_:
        env = await stack_.enter_async_context(await WorkflowEnvironment.start_time_skipping())
        app = create_app(
            settings,
            authorizer=authorizer,
            temporal=env.client,
            blobs=blobs,
            service_transport=Router(routes),
        )
        routes["governance"] = httpx.ASGITransport(app=app)
        for a in (*apps.values(), app):
            await stack_.enter_async_context(a.router.lifespan_context(a))
        api = await stack_.enter_async_context(
            httpx.AsyncClient(transport=routes["governance"], base_url="http://governance")
        )
        clients = {
            name: await stack_.enter_async_context(
                httpx.AsyncClient(transport=routes[name], base_url=f"http://{name}")
            )
            for name in SERVICES
        }
        yield Stack(tenants, api, clients, env, blobs, {**apps, "governance": app}, gov_db)
