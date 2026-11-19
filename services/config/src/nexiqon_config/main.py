"""Config registry: domain packs, agents, graphs, tools, model profiles, versions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_config import __version__
from nexiqon_config.api import public_router, tenant_router
from nexiqon_config.gate import Gate
from nexiqon_config.lifecycle import lifecycle
from nexiqon_config.models import Outbox
from nexiqon_config.settings import ServiceSettings
from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.bus import Bus, EventRuntime
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.directory import Topology
from nexiqon_core.flags import Flags

SERVICE_NAME: Final = "config"
PLANE: Final = "control"


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    bus: Bus | None = None,
    service_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Test seam: ``service_transport`` (the evaluation service, for release gates)."""
    settings = settings or ServiceSettings()
    evaluation_url = settings.evaluation_url
    if evaluation_url is None:
        try:
            evaluation_url = Topology.load(settings.groups_file).url_for("evaluation")
        except (OSError, KeyError, ValueError):
            evaluation_url = None
    gate = Gate(evaluation_url, transport=service_transport)
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
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
        await gate.aclose()
        if engine is not None:
            await engine.dispose()

    db = TenantSessionFactory(engine) if engine else None
    flags = Flags(settings.flags, service=SERVICE_NAME)
    events = None
    if settings.events.enabled and db is not None:
        events = EventRuntime(settings.events, SERVICE_NAME, bus)
        events.relay(db, Outbox)

    app = create_service_app(
        name=SERVICE_NAME,
        version=__version__,
        plane=PLANE,
        settings=settings,
        routers=[public_router],
        tenant_routers=[tenant_router],
        lifecycle=lifecycle(SERVICE_NAME),
        readiness_checks={"database": database_ready, "flags": flags.ready},
        lifespan=lifespan,
        authorizer=authorizer,
        events=events,
    )
    app.state.db = db
    app.state.flags = flags
    app.state.gate = gate
    return app
