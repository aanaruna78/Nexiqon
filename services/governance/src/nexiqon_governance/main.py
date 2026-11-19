"""Retention, tenant deletion/export sagas and their tracking (G-01, G-02)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
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
from nexiqon_core.lifecycle import NoTenantData
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_governance import __version__
from nexiqon_governance.api import public_router, tenant_router
from nexiqon_governance.models import Outbox
from nexiqon_governance.peers import Peers
from nexiqon_governance.runner import Runner, TenantRegistry
from nexiqon_governance.settings import ServiceSettings
from nexiqon_governance.workflows import WORKFLOWS

SERVICE_NAME: Final = "governance"
PLANE: Final = "control"
SCHEDULE_ID = "governance-retention-daily"
log = structlog.get_logger(__name__)


async def ensure_schedule(client: Any, settings: ServiceSettings) -> None:
    """The nightly platform-wide retention sweep (created once; existing schedules are kept)."""
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleAlreadyRunningError,
        ScheduleCalendarSpec,
        ScheduleRange,
        ScheduleSpec,
    )

    with suppress(ScheduleAlreadyRunningError):
        await client.create_schedule(
            SCHEDULE_ID,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    "governance.RetentionAll",
                    id="governance-retention-all",
                    task_queue=settings.task_queue,
                ),
                spec=ScheduleSpec(
                    calendars=[
                        ScheduleCalendarSpec(
                            hour=[ScheduleRange(settings.retention_hour_utc)],
                            minute=[ScheduleRange(0)],
                        )
                    ],
                    jitter=timedelta(minutes=30),
                ),
            ),
        )


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    bus: Bus | None = None,
    temporal: Any = None,
    blobs: BlobStore | None = None,
    service_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Test seams: ``temporal`` (a connected client), ``blobs``, ``service_transport`` (the
    lifecycle endpoints of every service)."""
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    blob_store = blobs or create_blob_store(settings.blobs)
    tokens = ServiceTokens(SERVICE_NAME, settings.context_token, settings.governance_identity)
    peers = Peers(settings, tokens, transport=service_transport)
    runner = Runner(db, peers, blob_store, settings.export_link_days) if db is not None else None
    events = None
    if settings.events.enabled and db is not None:
        events = EventRuntime(settings.events, SERVICE_NAME, bus)
        events.relay(db, Outbox)
        events.subscribe("governance-tenants", "nexiqon.identity.tenant.>", TenantRegistry(db))

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
                await ensure_schedule(app.state.temporal, settings)
            except Exception as exc:  # the dev time-skipping server has no schedules
                log.warning("retention_schedule_unavailable", error=str(exc))
        try:
            yield
        finally:
            if worker is not None and worker_task is not None:
                if not worker.is_shutdown:
                    await worker.shutdown()
                with suppress(asyncio.CancelledError):
                    await worker_task
            await peers.aclose()
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
        lifecycle=runner.own() if runner is not None else NoTenantData(SERVICE_NAME),
        readiness_checks=checks or None,
        lifespan=lifespan,
        authorizer=authorizer,
        events=events,
    )
    app.state.db = db
    app.state.blobs = blob_store
    app.state.peers = peers
    app.state.runner = runner
    app.state.temporal = temporal
    app.state.worker = None
    return app
