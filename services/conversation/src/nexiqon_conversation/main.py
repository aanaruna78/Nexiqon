"""Conversations: sessions, messages with answer contracts, feedback, retention."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Final

import httpx
import structlog
from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_conversation import __version__
from nexiqon_conversation.api import public_router, tenant_router
from nexiqon_conversation.lifecycle import lifecycle
from nexiqon_conversation.models import Outbox
from nexiqon_conversation.retention import sweep
from nexiqon_conversation.settings import ServiceSettings
from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.bus import Bus, EventRuntime
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.directory import Topology
from nexiqon_core.profiles import ProfileResolver

SERVICE_NAME: Final = "conversation"
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
    service_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    agent_client = httpx.AsyncClient(transport=service_transport, timeout=180.0, trust_env=False)
    retention_profiles = ProfileResolver(
        _url(settings, settings.config_url, "config"),
        settings.profile_environment,
        kind="retention_profile",
        transport=service_transport,
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

    async def sweeper() -> None:
        while True:
            await asyncio.sleep(settings.retention_sweep_seconds)
            try:
                removed = await sweep(db)  # type: ignore[arg-type]
                if removed:
                    log.info("retention_sweep", deleted=removed)
            except Exception as exc:
                log.warning("retention_sweep_failed", error=str(exc))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = (
            asyncio.create_task(sweeper())
            if db is not None and settings.retention_sweep_seconds > 0
            else None
        )
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await agent_client.aclose()
            await retention_profiles.aclose()
            if engine is not None:
                await engine.dispose()

    checks: dict[str, Callable[[], Awaitable[bool]]] = (
        {"database": database_ready} if engine is not None else {}
    )
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
    app.state.agent_client = agent_client
    app.state.agent_url = (
        u.rstrip("/")
        if (u := _url(settings, settings.agent_runtime_url, "agent-runtime"))
        else None
    )
    app.state.retention_profiles = retention_profiles
    return app
