"""Hybrid search, ACL filtering, small-to-big expansion and citation verification."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.directory import Topology
from nexiqon_core.profiles import ProfileResolver
from nexiqon_retrieval import __version__
from nexiqon_retrieval.adapters.pgvector import PgVectorStore
from nexiqon_retrieval.api import public_router, tenant_router
from nexiqon_retrieval.lifecycle import lifecycle
from nexiqon_retrieval.models_client import GatewayModelClient, ModelClient
from nexiqon_retrieval.search import Searcher
from nexiqon_retrieval.settings import ServiceSettings
from nexiqon_retrieval.store import VectorStore

SERVICE_NAME: Final = "retrieval"
PLANE: Final = "data"


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
    models: ModelClient | None = None,
    store: VectorStore | None = None,
    service_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Test seams: ``models`` (query embeddings/rerank), ``store``, ``service_transport`` (config)."""
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    model_client: ModelClient = models or GatewayModelClient(
        _url(settings, settings.model_gateway_url, "model-gateway"), transport=service_transport
    )
    profiles = ProfileResolver(
        _url(settings, settings.config_url, "config"),
        settings.profile_environment,
        kind="retrieval_profile",
        transport=service_transport,
    )
    vector_store = store or (PgVectorStore(db, settings.hnsw_ef_search) if db is not None else None)

    async def database_ready() -> bool:
        if engine is None:
            return False
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await model_client.aclose()
        await profiles.aclose()
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
    app.state.profiles = profiles
    app.state.searcher = Searcher(vector_store, model_client) if vector_store is not None else None
    return app
