"""Policy decisions (OPA) for role, resource and action authorization."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI

from nexiqon_authz import __version__
from nexiqon_authz.adapters.opa import OpaClient
from nexiqon_authz.api import public_router, tenant_router
from nexiqon_authz.lifecycle import lifecycle
from nexiqon_authz.settings import ServiceSettings
from nexiqon_core.app import create_service_app
from nexiqon_core.authz import StaticAuthorizer

SERVICE_NAME: Final = "authz"
PLANE: Final = "control"


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings()
    opa = OpaClient(settings.opa_url, settings.opa_decision_path, settings.opa_timeout_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await opa.aclose()

    app = create_service_app(
        name=SERVICE_NAME,
        version=__version__,
        plane=PLANE,
        settings=settings,
        routers=[public_router],
        tenant_routers=[tenant_router],
        lifecycle=lifecycle(SERVICE_NAME),
        readiness_checks={"opa": opa.healthy},
        lifespan=lifespan,
        # authz does not call itself; its own routes are open to any verified actor.
        authorizer=StaticAuthorizer({}),
    )
    app.state.opa = opa
    return app
