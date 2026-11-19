"""Usage and cost read models, budgets and alerts, quality and content-gap insights."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Final

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.bus import Bus, EventRuntime
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.directory import Topology
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_metering import __version__
from nexiqon_metering.api import public_router, tenant_router
from nexiqon_metering.clients import Peers
from nexiqon_metering.lifecycle import lifecycle
from nexiqon_metering.models import Outbox
from nexiqon_metering.recorder import SUBJECTS, Recorder
from nexiqon_metering.settings import ServiceSettings

SERVICE_NAME: Final = "metering"
PLANE: Final = "control"


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
    """Test seams: ``bus`` (in-memory events) and ``service_transport`` (config, conversation)."""
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    recorder = Recorder(db) if db is not None else None
    events = None
    if settings.events.enabled and db is not None and recorder is not None:
        events = EventRuntime(settings.events, SERVICE_NAME, bus)
        events.relay(db, Outbox)
        events.subscribe("metering", SUBJECTS, recorder)
    peers = Peers(
        ServiceTokens(SERVICE_NAME, settings.context_token, settings.metering_identity),
        _url(settings, settings.config_url, "config"),
        _url(settings, settings.conversation_url, "conversation"),
        settings.profile_environment,
        transport=service_transport,
    )

    async def database_ready() -> bool:
        if engine is None:
            return False
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await peers.aclose()
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
    app.state.recorder = recorder
    app.state.peers = peers
    return app
