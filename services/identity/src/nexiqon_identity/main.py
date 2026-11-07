"""Tenants, users, memberships, IdP adapters and tenant-context tokens."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_identity import __version__
from nexiqon_identity.access import AccessPolicy, AccessService
from nexiqon_identity.adapters.oidc import JwksFetcher, OidcVerifier, http_fetch_jwks
from nexiqon_identity.api import public_router, tenant_router
from nexiqon_identity.keys import build_issuer
from nexiqon_identity.lifecycle import lifecycle
from nexiqon_identity.settings import ServiceSettings
from nexiqon_identity.webhooks import ClerkWebhooks

SERVICE_NAME: Final = "identity"
PLANE: Final = "control"


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    jwks_fetcher: JwksFetcher = http_fetch_jwks,
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
        lifecycle=lifecycle(SERVICE_NAME),
        readiness_checks={"database": database_ready},
        lifespan=lifespan,
        authorizer=authorizer,
    )
    issuer = build_issuer(settings.signing, settings.context_token, settings.context_ttl_seconds)
    app.state.db = db
    app.state.access = (
        AccessService(
            db,
            OidcVerifier(settings.idp_providers, jwks_fetcher),
            issuer,
            AccessPolicy(
                jit_provisioning=settings.jit_provisioning,
                require_admin_mfa=settings.require_admin_mfa,
                cache_seconds=settings.context_cache_seconds,
            ),
        )
        if db is not None
        else None
    )
    clerk = next((p for p in settings.idp_providers if p.kind == "clerk"), None)
    app.state.clerk_webhooks = ClerkWebhooks(db, clerk) if (db is not None and clerk) else None
    return app
