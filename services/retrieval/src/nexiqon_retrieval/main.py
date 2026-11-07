"""Hybrid search, ACL filtering, small-to-big expansion and citation verification."""

from typing import Final

from fastapi import FastAPI

from nexiqon_core.app import create_service_app
from nexiqon_retrieval import __version__
from nexiqon_retrieval.api import public_router, tenant_router
from nexiqon_retrieval.lifecycle import lifecycle
from nexiqon_retrieval.settings import ServiceSettings

SERVICE_NAME: Final = "retrieval"
PLANE: Final = "data"


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
