"""Config registry: domain packs, agents, graphs, tools, model profiles, versions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_config import __version__
from nexiqon_config.api import public_router, tenant_router
from nexiqon_config.lifecycle import lifecycle
from nexiqon_config.settings import ServiceSettings
from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.db import TenantSessionFactory, create_engine

SERVICE_NAME: Final = "config"
PLANE: Final = "control"


def create_app(
    settings: ServiceSettings | None = None, *, authorizer: Authorizer | None = None
) -> FastAPI:
    settings = settings or ServiceSettings()
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
    )
    app.state.db = TenantSessionFactory(engine) if engine else None
    return app
