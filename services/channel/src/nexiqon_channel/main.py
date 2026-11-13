"""Channel adapters (web widget, API) and their settings (CH-01)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

import httpx
from fastapi import FastAPI

from nexiqon_channel import __version__
from nexiqon_channel.api import Agents, public_router, tenant_router
from nexiqon_channel.lifecycle import lifecycle
from nexiqon_channel.settings import ServiceSettings
from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.directory import Topology
from nexiqon_core.service_auth import ServiceTokens

SERVICE_NAME: Final = "channel"
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
    service_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or ServiceSettings()
    identity = (
        settings.channel_identity if settings.channel_identity.key_id else settings.service_identity
    )
    agents = Agents(
        _config_url(settings),
        ServiceTokens(SERVICE_NAME, settings.context_token, identity),
        settings.agent_environment,
        settings.settings_cache_seconds,
        service_transport,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await agents.aclose()

    app = create_service_app(
        name=SERVICE_NAME,
        version=__version__,
        plane=PLANE,
        settings=settings,
        routers=[public_router],
        tenant_routers=[tenant_router],
        lifecycle=lifecycle(SERVICE_NAME),
        lifespan=lifespan,
        authorizer=authorizer,
    )
    app.state.agents = agents
    return app
