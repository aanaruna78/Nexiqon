"""evaluation fixtures: Postgres, Temporal (time-skipping), the real config service (versions and
release gates) and a scripted agent-runtime that records what evaluation asked."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from temporalio.testing import WorkflowEnvironment

from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, ContextTokenVerifier, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair
from nexiqon_evaluation.main import create_app
from nexiqon_evaluation.settings import ServiceSettings

ROOT = Path(__file__).resolve().parents[3]
PACK = (ROOT / "packs/saas-knowledge-assistant/pack.yaml").read_text()
SVC_PRIVATE, SVC_PUBLIC = make_keypair()
# Mirrors services/authz/policies for the actions used here. Editors may not override a gate
# (config.release.override is admin-only in the policy).
ROLES = {
    "owner": ["**"],
    "admin": ["**"],
    "editor": [
        "**.read",
        "config.agent.write",
        "config.domain_pack.write",
        "config.deployments.write",
        "evaluation.**",
    ],
    "member": ["**.read"],
    "service:evaluation": [
        "agent.query.run",
        "agent.versions.preview",
        "config.agent.read",
    ],
}
AGENT = "helper"


def ok(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json() if r.content else None


@pytest.fixture(scope="session")
def eval_db(postgres: PgUrls) -> PgUrls:
    upgrade("config", postgres.owner, postgres.app_role)
    upgrade("evaluation", postgres.owner, postgres.app_role)
    return postgres


@dataclass
class FakeAgents:
    """agent-runtime as evaluation sees it. ``answers[version][question]`` is the answer body;
    unknown questions get an abstention."""

    verifier: ContextTokenVerifier
    answers: dict[int, dict[str, dict[str, Any]]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    def grounded(self, version: int, question: str, text: str, doc: str, section: str) -> None:
        self.answers.setdefault(version, {})[question] = {
            "text": text,
            "abstained": False,
            "kind": "grounded",
            "citations": [
                {
                    "marker": "1",
                    "citation": f"{doc.removesuffix('.md').title()} \u203a {section}",
                    "source_uri": f"upload://{doc}",
                }
            ],
        }

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        ctx = self.verifier.verify(request.headers[CONTEXT_HEADER])
        body = json.loads(request.content)
        self.calls.append({"ctx": ctx, "path": request.url.path, **body})
        if self.fail:
            return httpx.Response(503, json={"code": "service_unavailable"})
        version = int(body["version"])
        answer = self.answers.get(version, {}).get(body["input"]) or {
            "text": "I could not find that in the documentation.",
            "abstained": True,
            "kind": "grounded",
            "citations": [],
        }
        return httpx.Response(
            200,
            json={
                "run_id": f"run-{len(self.calls)}",
                "status": "done",
                "answer": answer,
                "interrupt": None,
                "handoff": None,
                "intent": None,
                "route": "answer",
                "steps": [],
                "error": None,
                "retention_profile": None,
                "usage": {"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.001},
            },
        )


class Router(httpx.AsyncBaseTransport):
    def __init__(self, routes: dict[str, httpx.AsyncBaseTransport]) -> None:
        self.routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.routes[request.url.host].handle_async_request(request)


@dataclass
class Stack:
    tenants: TwoTenants
    api: httpx.AsyncClient  # evaluation
    config: httpx.AsyncClient
    env: WorkflowEnvironment
    agents: FakeAgents
    app: Any

    def headers(self, *roles: str, tenant: str = "a", actor: str = "user-a") -> dict[str, str]:
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        ctx = TenantContext(t, actor, "user", frozenset(roles or {"owner"}))
        return {CONTEXT_HEADER: self.tenants.issuer.issue(ctx)}

    @property
    def h(self) -> dict[str, str]:
        return self.headers("owner")

    async def ok(self, method: str, url: str, status: int = 200, **kw: Any) -> Any:
        r = await self.api.request(method, url, headers=kw.pop("headers", self.h), **kw)
        return ok(r, status)

    async def cfg(self, method: str, url: str, status: int = 200, **kw: Any) -> Any:
        r = await self.config.request(method, url, headers=kw.pop("headers", self.h), **kw)
        return ok(r, status)

    async def draft(self, spec: dict[str, Any]) -> int:
        """Save a draft of the assistant; returns its version number."""
        existing = await self.config.get(f"/v1/objects/agent/{AGENT}", headers=self.h)
        if existing.status_code == 404:
            v = await self.cfg(
                "POST", "/v1/objects", 201, json={"kind": "agent", "name": AGENT, "spec": spec}
            )
            return max(int(x["version"]) for x in v["versions"])
        v = await self.cfg("PUT", f"/v1/objects/agent/{AGENT}/draft", json={"spec": spec})
        return int(v["version"])

    async def run(self, version: int, test_set_id: str) -> dict[str, Any]:
        """Evaluate a version and wait for the workflow (time-skipping)."""
        started = await self.ok(
            "POST",
            "/v1/runs",
            202,
            json={"agent": AGENT, "version": version, "test_set_id": test_set_id},
        )
        tenant = self.tenants.a.context.tenant_id
        await self.env.client.get_workflow_handle(f"{tenant}:evaluation:{started['id']}").result()
        result: dict[str, Any] = await self.ok("GET", f"/v1/runs/{started['id']}")
        return result


def spec(**extra: Any) -> dict[str, Any]:
    return {"pack": {"name": "saas-knowledge-assistant"}, "display_name": "Helper", **extra}


@pytest.fixture
async def stack(eval_db: PgUrls) -> AsyncIterator[Stack]:
    tenants = TwoTenants.create(roles=frozenset({"owner"}))
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc-eval": SVC_PUBLIC},
        service_keys={"svc-eval": "evaluation"},
    )
    authorizer = StaticAuthorizer(ROLES)
    db = DatabaseSettings(url=eval_db.app, pool_size=0)
    agents = FakeAgents(ContextTokenVerifier(tokens))
    routes: dict[str, httpx.AsyncBaseTransport] = {"agent-runtime": httpx.MockTransport(agents)}
    config_app = create_config_app(
        ConfigSettings(
            log_json=False, context_token=tokens, database=db, evaluation_url="http://evaluation"
        ),
        authorizer=authorizer,
        service_transport=Router(routes),
    )
    routes["config"] = httpx.ASGITransport(app=config_app)
    settings = ServiceSettings(
        log_json=False,
        context_token=tokens,
        database=db,
        evaluation_identity=ServiceIdentitySettings(key_id="svc-eval", private_key=SVC_PRIVATE),  # type: ignore[arg-type]
        agent_runtime_url="http://agent-runtime",
        config_url="http://config",
        task_queue="evaluation-test",
        worker_max_cached_workflows=0,
        pack_gallery_dir=ROOT / "packs",
    )
    async with AsyncExitStack() as stack_:
        env = await stack_.enter_async_context(await WorkflowEnvironment.start_time_skipping())
        app = create_app(
            settings, authorizer=authorizer, temporal=env.client, service_transport=Router(routes)
        )
        routes["evaluation"] = httpx.ASGITransport(app=app)
        for a in (config_app, app):
            await stack_.enter_async_context(a.router.lifespan_context(a))
        api = await stack_.enter_async_context(
            httpx.AsyncClient(transport=routes["evaluation"], base_url="http://evaluation")
        )
        config = await stack_.enter_async_context(
            httpx.AsyncClient(transport=routes["config"], base_url="http://config")
        )
        s = Stack(tenants, api, config, env, agents, app)
        await s.cfg(
            "POST",
            "/v1/packs/import",
            201,
            content=PACK,
            headers={**s.h, "content-type": "application/yaml"},
        )
        await s.cfg("POST", "/v1/objects/domain_pack/saas-knowledge-assistant/versions/1/publish")
        await s.cfg(
            "PUT",
            "/v1/objects/domain_pack/saas-knowledge-assistant/deployments/dev",
            json={"version": 1},
        )
        yield s
