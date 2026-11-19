"""Test sets, evaluation runs, scorecards and release gates (QA-01, QA-02)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any, Final

import httpx
import structlog
from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.bus import Bus, EventRuntime
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.directory import Topology
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_evaluation import __version__
from nexiqon_evaluation.api import public_router, tenant_router
from nexiqon_evaluation.clients import AgentRuntime, Config
from nexiqon_evaluation.evaluators import GROUP, builtin
from nexiqon_evaluation.lifecycle import lifecycle
from nexiqon_evaluation.models import Outbox
from nexiqon_evaluation.runner import Runner
from nexiqon_evaluation.settings import ServiceSettings
from nexiqon_evaluation.workflows import WORKFLOWS
from nexiqon_sdk import Registry

SERVICE_NAME: Final = "evaluation"
PLANE: Final = "control"
log = structlog.get_logger(__name__)


def _url(settings: ServiceSettings, explicit: str | None, service: str) -> str | None:
    if explicit:
        return explicit
    try:
        return Topology.load(settings.groups_file).url_for(service)
    except (OSError, KeyError, ValueError):
        return None


def evaluator_registry() -> Registry:
    registry = Registry()
    for plugin in builtin():
        registry.register(plugin)
    registry.discover(GROUP)
    return registry


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    bus: Bus | None = None,
    temporal: Any = None,
    registry: Registry | None = None,
    service_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Test seams: ``temporal`` (a connected client), ``service_transport`` (agent-runtime)."""
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    registry = registry or evaluator_registry()
    tokens = ServiceTokens(SERVICE_NAME, settings.context_token, settings.evaluation_identity)
    agents = AgentRuntime(
        _url(settings, settings.agent_runtime_url, "agent-runtime"),
        transport=service_transport,
        timeout=float(settings.case_timeout_seconds),
    )
    config = Config(_url(settings, settings.config_url, "config"), transport=service_transport)
    runner = Runner(db, tokens, agents, registry, config) if db is not None else None
    events = None
    if settings.events.enabled and db is not None:
        events = EventRuntime(settings.events, SERVICE_NAME, bus)
        events.relay(db, Outbox)

    async def database_ready() -> bool:
        if engine is None:
            return False
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    async def workflows_ready() -> bool:
        return app.state.temporal is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        worker_task: asyncio.Task[None] | None = None
        worker = None
        if app.state.temporal is None and settings.workflows.enabled:
            from nexiqon_core.workflows import connect

            try:
                app.state.temporal = await connect(settings.workflows)
            except Exception as exc:
                log.warning("temporal_unavailable", error=str(exc))
        if app.state.temporal is not None and runner is not None and settings.run_worker:
            from temporalio.worker import Worker

            worker = Worker(
                app.state.temporal,
                task_queue=settings.task_queue,
                workflows=WORKFLOWS,
                activities=runner.activities(),
                max_cached_workflows=settings.worker_max_cached_workflows,
            )
            worker_task = asyncio.create_task(worker.run())
            app.state.worker = worker
        try:
            yield
        finally:
            if worker is not None and worker_task is not None:
                if not worker.is_shutdown:
                    await worker.shutdown()
                with suppress(asyncio.CancelledError):
                    await worker_task
            await agents.aclose()
            await config.aclose()
            if engine is not None:
                await engine.dispose()

    checks: dict[str, Callable[[], Awaitable[bool]]] = (
        {"database": database_ready} if engine is not None else {}
    )
    if settings.workflows.enabled:
        checks["workflows"] = workflows_ready
    app = create_service_app(
        name=SERVICE_NAME,
        version=__version__,
        plane=PLANE,
        settings=settings,
        routers=[public_router],
        tenant_routers=[tenant_router],
        lifecycle=lifecycle(SERVICE_NAME, db),
        readiness_checks=checks or None,
        lifespan=lifespan,
        authorizer=authorizer,
        events=events,
    )
    app.state.db = db
    app.state.registry = registry
    app.state.runner = runner
    app.state.tokens = tokens
    app.state.config_client = config
    app.state.temporal = temporal
    app.state.worker = None
    return app
