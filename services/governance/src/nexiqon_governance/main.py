"""Retention, tenant deletion/export sagas and data-subject requests."""

from typing import Final

from fastapi import FastAPI

from nexiqon_core.app import create_service_app
from nexiqon_governance import __version__
from nexiqon_governance.api import public_router, tenant_router
from nexiqon_governance.lifecycle import lifecycle
from nexiqon_governance.settings import ServiceSettings

SERVICE_NAME: Final = "governance"
PLANE: Final = "control"


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings()
    return create_service_app(
        name=SERVICE_NAME,
        version=__version__,
        plane=PLANE,
        settings=settings,
        routers=[public_router],
        tenant_routers=[tenant_router],
        lifecycle=lifecycle(SERVICE_NAME),
    )
