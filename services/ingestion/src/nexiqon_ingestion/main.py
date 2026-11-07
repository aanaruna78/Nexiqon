"""Source connectors, parsing, chunking, embedding and document lifecycle."""

from typing import Final

from fastapi import FastAPI

from nexiqon_core.app import create_service_app
from nexiqon_ingestion import __version__
from nexiqon_ingestion.api import public_router, tenant_router
from nexiqon_ingestion.lifecycle import lifecycle
from nexiqon_ingestion.settings import ServiceSettings

SERVICE_NAME: Final = "ingestion"
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
