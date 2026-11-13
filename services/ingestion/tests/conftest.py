"""Ingestion end to end: real Postgres, Temporal test server, real config + retrieval services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from temporalio.testing import WorkflowEnvironment

from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.blobs import MemoryBlobStore
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.testing import TwoTenants, make_keypair
from nexiqon_ingestion.main import create_app
from nexiqon_ingestion.settings import ServiceSettings
from nexiqon_ingestion.testing import FakeModelGateway, FakeScanner, FakeWeb, HostRouter
from nexiqon_retrieval.main import create_app as create_retrieval_app
from nexiqon_retrieval.settings import ServiceSettings as RetrievalSettings

# Mirrors services/authz/policies for the actions used here.
SERVICE_ROLE = [
    "config.profiles.resolve",
    "model.inference.run",
    "retrieval.index.write",
    "retrieval.index.read",
]
ROLES = {
    "owner": ["**"],
    "editor": ["**.read", "ingestion.**", "retrieval.index.read", "config.profiles.resolve"],
    "member": ["**.read"],
    "service:ingestion": SERVICE_ROLE,
}
SVC_PRIVATE, SVC_PUBLIC = make_keypair()


@pytest.fixture(scope="session")
def knowledge_db(postgres: PgUrls) -> PgUrls:
    for service in ("config", "retrieval", "ingestion"):
        upgrade(service, postgres.owner, postgres.app_role)
    return postgres


@dataclass
class Stack:
    tenants: TwoTenants
    api: httpx.AsyncClient
    retrieval: httpx.AsyncClient
    env: WorkflowEnvironment
    gateway: FakeModelGateway
    web: FakeWeb
    blobs: MemoryBlobStore
    app: Any

    @property
    def h(self) -> dict[str, str]:
        return self.tenants.a.headers

    async def ok(self, method: str, url: str, status: int = 200, **kw: Any) -> Any:
        r = await self.api.request(method, url, headers=kw.pop("headers", self.h), **kw)
        assert r.status_code == status, r.text
        return r.json() if r.content else None

    async def wait(self, run: dict[str, Any]) -> dict[str, Any]:
        """Wait for a run's workflow (time-skipping), then return the run."""
        await self.env.client.get_workflow_handle(run["workflow_id"]).result()
        result: dict[str, Any] = await self.ok("GET", f"/v1/runs/{run['id']}")
        return result

    async def collection(self, name: str = "kb", **extra: Any) -> dict[str, Any]:
        out: dict[str, Any] = await self.ok(
            "POST", "/v1/collections", 201, json={"name": name, **extra}
        )
        return out

    async def upload(
        self, collection_id: str, filename: str, body: bytes, media: str
    ) -> dict[str, Any]:
        out: dict[str, Any] = await self.ok(
            "POST",
            f"/v1/collections/{collection_id}/documents",
            202,
            params={"filename": filename},
            content=body,
            headers={**self.h, "content-type": media},
        )
        return out


StackFactory = Callable[..., Any]


@pytest.fixture
async def stack(knowledge_db: PgUrls, tmp_path: Path) -> AsyncIterator[Stack]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-ingestion": SVC_PUBLIC},
        service_keys={"svc-ingestion": "ingestion"},
    )
    authorizer = StaticAuthorizer(ROLES)
    db = DatabaseSettings(url=knowledge_db.app, pool_size=0)
    config_app = create_config_app(
        ConfigSettings(log_json=False, context_token=tokens, database=db), authorizer=authorizer
    )
    retrieval_app = create_retrieval_app(
        RetrievalSettings(log_json=False, context_token=tokens, database=db), authorizer=authorizer
    )
    gateway = FakeModelGateway()
    web = FakeWeb()
    blobs = MemoryBlobStore()
    router = HostRouter(
        {
            "config": httpx.ASGITransport(app=config_app),
            "retrieval": httpx.ASGITransport(app=retrieval_app),
            "model-gateway": httpx.MockTransport(gateway),
        }
    )
    settings = ServiceSettings(
        log_json=False,
        context_token=tokens,
        service_identity=ServiceIdentitySettings(key_id="svc-ingestion", private_key=SVC_PRIVATE),  # type: ignore[arg-type]
        database=db,
        config_url="http://config",
        retrieval_url="http://retrieval",
        model_gateway_url="http://model-gateway",
        task_queue="ingestion-test",
        scratch_dir=tmp_path / "scratch",
        embed_batch_size=8,
        worker_max_cached_workflows=0,  # no sticky queues: a restarted worker resumes at once
    )
    async with AsyncExitStack() as stack:
        env = await stack.enter_async_context(await WorkflowEnvironment.start_time_skipping())
        app = create_app(
            settings,
            authorizer=authorizer,
            temporal=env.client,
            blobs=blobs,
            scanner=FakeScanner(),
            service_transport=router,
            fetch_transport=httpx.MockTransport(web),
            fetch_resolver=web.resolve,
        )
        for a in (config_app, retrieval_app, app):
            await stack.enter_async_context(a.router.lifespan_context(a))
        api = await stack.enter_async_context(
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ingestion")
        )
        retrieval = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=retrieval_app), base_url="http://retrieval"
            )
        )
        yield Stack(tenants, api, retrieval, env, gateway, web, blobs, app)
