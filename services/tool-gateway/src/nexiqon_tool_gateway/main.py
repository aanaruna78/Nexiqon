"""Tool gateway: registry from config, authorisation, validation, egress control, approvals."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Final

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.bus import Bus, EventRuntime
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.directory import Topology
from nexiqon_core.fetch import SafeFetcher
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_tool_gateway import __version__
from nexiqon_tool_gateway.api import public_router, tenant_router
from nexiqon_tool_gateway.guards import Guards
from nexiqon_tool_gateway.lifecycle import lifecycle
from nexiqon_tool_gateway.models import Outbox
from nexiqon_tool_gateway.registry import Registry
from nexiqon_tool_gateway.secrets import MemorySecrets, Secrets, UnconfiguredSecrets
from nexiqon_tool_gateway.settings import ServiceSettings

SERVICE_NAME: Final = "tool-gateway"
PLANE: Final = "data"


def _url(settings: ServiceSettings, explicit: str | None, service: str) -> str | None:
    if explicit:
        return explicit
    try:
        return Topology.load(settings.groups_file).url_for(service)
    except (OSError, KeyError, ValueError):
        return None


def _secrets(settings: ServiceSettings) -> Secrets:
    if settings.secrets.backend == "memory":
        return MemorySecrets()
    from nexiqon_tool_gateway.adapters.openbao import OpenBaoSecrets

    if settings.secrets.token is None:
        return UnconfiguredSecrets()
    return OpenBaoSecrets(
        settings.secrets.address, settings.secrets.token.get_secret_value(), settings.secrets.mount
    )


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    bus: Bus | None = None,
    secrets: Secrets | None = None,
    config_transport: httpx.AsyncBaseTransport | None = None,
    egress_transport: httpx.AsyncBaseTransport | None = None,
    egress_resolver: Any = None,
) -> FastAPI:
    """Test seams: ``secrets``, ``config_transport`` and the egress transport/resolver."""
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    store = secrets or _secrets(settings)
    tokens = ServiceTokens(SERVICE_NAME, settings.context_token, settings.service_identity)
    registry = Registry(
        _url(settings, settings.config_url, "config"),
        tokens,
        settings.tool_environment,
        settings.definition_cache_seconds,
        transport=config_transport,
    )
    fetcher = SafeFetcher(settings.egress, resolver=egress_resolver, transport=egress_transport)
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
        await registry.aclose()
        await fetcher.aclose()
        closer = getattr(store, "aclose", None)
        if closer is not None:
            await closer()
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
        lifecycle=lifecycle(SERVICE_NAME, db, store),
        readiness_checks=checks or None,
        lifespan=lifespan,
        authorizer=authorizer,
        events=events,
    )
    app.state.db = db
    app.state.registry = registry
    app.state.secrets = store
    app.state.fetcher = fetcher
    app.state.guards = Guards(settings.circuit_failures, settings.circuit_cooldown_seconds)
    return app
