"""Append-only, hash-chained audit log."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_audit import __version__
from nexiqon_audit.api import public_router, tenant_router
from nexiqon_audit.lifecycle import lifecycle
from nexiqon_audit.recorder import Recorder
from nexiqon_audit.settings import ServiceSettings
from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.bus import Bus, EventRuntime
from nexiqon_core.db import TenantSessionFactory, create_engine

SERVICE_NAME: Final = "audit"
PLANE: Final = "control"


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    bus: Bus | None = None,
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
    events = None
    if settings.events.enabled and db is not None:
        events = EventRuntime(settings.events, SERVICE_NAME, bus)
        events.subscribe("audit", "nexiqon.>", Recorder(db))

    async def database_ready() -> bool:
        if engine is None:
            return False
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            await engine.dispose()

    app = create_service_app(
        name=SERVICE_NAME,
        version=__version__,
        plane=PLANE,
        settings=settings,
        routers=[public_router],
        tenant_routers=[tenant_router],
        lifecycle=lifecycle(SERVICE_NAME),
        readiness_checks={"database": database_ready},
        lifespan=lifespan,
        authorizer=authorizer,
        events=events,
    )
    app.state.db = db
    return app
