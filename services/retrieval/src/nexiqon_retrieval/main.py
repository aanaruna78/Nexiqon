"""Hybrid search, ACL filtering, small-to-big expansion and citation verification."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_retrieval import __version__
from nexiqon_retrieval.api import public_router, tenant_router
from nexiqon_retrieval.lifecycle import lifecycle
from nexiqon_retrieval.settings import ServiceSettings

SERVICE_NAME: Final = "retrieval"
PLANE: Final = "data"


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
    db = TenantSessionFactory(engine) if engine else None

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
        lifecycle=lifecycle(SERVICE_NAME, db),
        readiness_checks={"database": database_ready} if engine is not None else None,
        lifespan=lifespan,
        authorizer=authorizer,
    )
    app.state.db = db
    return app
