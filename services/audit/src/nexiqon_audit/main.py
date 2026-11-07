"""Append-only, hash-chained audit log."""

from typing import Final

from fastapi import FastAPI

from nexiqon_audit import __version__
from nexiqon_audit.api import public_router, tenant_router
from nexiqon_audit.lifecycle import lifecycle
from nexiqon_audit.settings import ServiceSettings
from nexiqon_core.app import create_service_app

SERVICE_NAME: Final = "audit"
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
