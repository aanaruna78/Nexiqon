"""LLM, embedding and reranker providers with routing, budgets and redaction."""

from collections.abc import AsyncIterator
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
from nexiqon_model_gateway import __version__
from nexiqon_model_gateway.adapters.registry import Providers
from nexiqon_model_gateway.api import public_router, tenant_router
from nexiqon_model_gateway.gateway import Gateway
from nexiqon_model_gateway.lifecycle import lifecycle
from nexiqon_model_gateway.models import Outbox
from nexiqon_model_gateway.pricing import PriceBook
from nexiqon_model_gateway.resolver import ProfileResolver
from nexiqon_model_gateway.settings import ServiceSettings

SERVICE_NAME: Final = "model-gateway"
PLANE: Final = "data"


def _config_url(settings: ServiceSettings) -> str | None:
    if settings.config_url:
        return settings.config_url
    try:
        return Topology.load(settings.groups_file).url_for("config")
    except (OSError, KeyError, ValueError):
        return None


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    bus: Bus | None = None,
    provider_transport: httpx.AsyncBaseTransport | None = None,
    config_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """``provider_transport``/``config_transport`` let tests run without real networks."""
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    gateway = Gateway(
        settings,
        ProfileResolver(
            _config_url(settings),
            settings.profile_environment,
            cache_seconds=settings.profile_cache_seconds,
            transport=config_transport,
        ),
        Providers(
            settings.providers, provider_transport, allow_offline=settings.allow_offline_provider
        ),
        PriceBook.load(settings.prices_file),
        db,
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await gateway.aclose()
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
        events=events,
    )
    app.state.gateway = gateway
    return app
