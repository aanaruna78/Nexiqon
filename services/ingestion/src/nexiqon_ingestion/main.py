"""Source connectors, parsing, chunking, embedding and document lifecycle."""

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
from nexiqon_core.blobs import BlobStore, create_blob_store
from nexiqon_core.bus import Bus, EventRuntime
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.directory import Topology
from nexiqon_core.fetch import SafeFetcher
from nexiqon_core.profiles import ProfileResolver
from nexiqon_core.scanning import Scanner, create_scanner
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_ingestion import __version__
from nexiqon_ingestion.api import public_router, tenant_router
from nexiqon_ingestion.clients import Embedder, IndexClient
from nexiqon_ingestion.lifecycle import lifecycle
from nexiqon_ingestion.models import Outbox
from nexiqon_ingestion.pipeline import Deps, Pipeline
from nexiqon_ingestion.settings import ServiceSettings
from nexiqon_ingestion.workflows import WORKFLOWS
from nexiqon_sdk import Registry

SERVICE_NAME: Final = "ingestion"
PLANE: Final = "data"
log = structlog.get_logger(__name__)


def _url(settings: ServiceSettings, explicit: str | None, service: str) -> str | None:
    if explicit:
        return explicit
    try:
        return Topology.load(settings.groups_file).url_for(service)
    except (OSError, KeyError, ValueError):
        return None


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    bus: Bus | None = None,
    temporal: Any = None,
    blobs: BlobStore | None = None,
    scanner: Scanner | None = None,
    registry: Registry | None = None,
    service_transport: httpx.AsyncBaseTransport | None = None,
    fetch_transport: httpx.AsyncBaseTransport | None = None,
    fetch_resolver: Any = None,
) -> FastAPI:
    """Test seams: ``temporal`` (a connected client), ``service_transport`` (config, model
    gateway, retrieval), ``fetch_transport``/``fetch_resolver`` (the web), blobs and scanner."""
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    if registry is None:
        registry = Registry()
        registry.discover()
    blob_store = blobs or create_blob_store(settings.blobs)
    tokens = ServiceTokens(SERVICE_NAME, settings.context_token, settings.service_identity)
    fetcher = SafeFetcher(settings.fetch, resolver=fetch_resolver, transport=fetch_transport)
    pipeline: Pipeline | None = None
    if db is not None:
        pipeline = Pipeline(
            Deps(
                settings=settings,
                db=db,
                blobs=blob_store,
                scanner=scanner or create_scanner(settings.scan),
                registry=registry,
                fetcher=fetcher,
                tokens=tokens,
                embedder=Embedder(
                    _url(settings, settings.model_gateway_url, "model-gateway"),
                    tokens,
                    transport=service_transport,
                ),
                index=IndexClient(
                    _url(settings, settings.retrieval_url, "retrieval"),
                    tokens,
                    transport=service_transport,
                ),
                retrieval_profiles=ProfileResolver(
                    _url(settings, settings.config_url, "config"),
                    settings.profile_environment,
                    kind="retrieval_profile",
                    transport=service_transport,
                ),
                connector_transport=fetch_transport,
            )
        )
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
        ensure = getattr(blob_store, "ensure", None)
        if ensure is not None:
            try:
                await ensure()
            except Exception as exc:
                log.warning("blob_store_unavailable", error=str(exc))
        if app.state.temporal is None and settings.workflows.enabled:
            from nexiqon_core.workflows import connect

            try:
                app.state.temporal = await connect(settings.workflows)
            except Exception as exc:
                log.warning("temporal_unavailable", error=str(exc))
        if app.state.temporal is not None and pipeline is not None and settings.run_worker:
            from temporalio.worker import Worker

            worker = Worker(
                app.state.temporal,
                task_queue=settings.task_queue,
                workflows=WORKFLOWS,
                activities=pipeline.activities(),
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
            if pipeline is not None:
                for closer in (
                    pipeline.d.embedder,
                    pipeline.d.index,
                    pipeline.d.retrieval_profiles,
                    pipeline.d.fetcher,
                ):
                    await closer.aclose()
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
        lifecycle=lifecycle(SERVICE_NAME, db, blob_store),
        readiness_checks=checks or None,
        lifespan=lifespan,
        authorizer=authorizer,
        events=events,
    )
    app.state.pipeline = pipeline
    app.state.registry = registry
    app.state.temporal = temporal
    app.state.worker = None
    return app
