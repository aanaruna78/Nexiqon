"""Declarative LangGraph agent execution."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Final

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_agent_runtime import __version__
from nexiqon_agent_runtime.api import public_router, tenant_router
from nexiqon_agent_runtime.clients import (
    Http,
    HttpTools,
    Models,
    NoTools,
    Retrieval,
    ServiceReads,
    Tools,
)
from nexiqon_agent_runtime.engine import Engine
from nexiqon_agent_runtime.lifecycle import lifecycle
from nexiqon_agent_runtime.settings import ServiceSettings
from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.directory import Topology
from nexiqon_core.service_auth import ServiceTokens

SERVICE_NAME: Final = "agent-runtime"
PLANE: Final = "data"
# LangGraph ships LangSmith tracing; customer data must never leave through it.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"


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
    service_transport: httpx.AsyncBaseTransport | None = None,
    tools: Tools | None = None,
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
    tokens = ServiceTokens(SERVICE_NAME, settings.context_token, settings.service_identity)

    def http(explicit: str | None, service: str) -> Http:
        return Http(_url(settings, explicit, service), service_transport)

    models = Models(_url(settings, settings.model_gateway_url, "model-gateway"), service_transport)
    retrieval = Retrieval(_url(settings, settings.retrieval_url, "retrieval"), service_transport)
    config, ingestion = (
        http(settings.config_url, "config"),
        http(settings.ingestion_url, "ingestion"),
    )
    reads = ServiceReads(
        config, ingestion, tokens, settings.agent_environment, settings.agent_cache_seconds
    )
    tool_url = _url(settings, settings.tool_gateway_url, "tool-gateway")
    tool_port: Tools = tools or (HttpTools(tool_url, service_transport) if tool_url else NoTools())
    runtime = Engine(settings, db, reads, models, retrieval, tool_port) if db is not None else None

    async def database_ready() -> bool:
        if engine is None:
            return False
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        for client in (models, retrieval, config, ingestion):
            await client.aclose()
        if isinstance(tool_port, Http):
            await tool_port.aclose()
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
    )
    app.state.engine = runtime
    return app
