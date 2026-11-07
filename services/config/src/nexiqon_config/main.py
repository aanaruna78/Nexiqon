"""Config registry: domain packs, agents, graphs, tools, model profiles, versions."""

from typing import Final

from fastapi import FastAPI

from nexiqon_config import __version__
from nexiqon_config.api import public_router, tenant_router
from nexiqon_config.lifecycle import lifecycle
from nexiqon_config.settings import ServiceSettings
from nexiqon_core.app import create_service_app

SERVICE_NAME: Final = "config"
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
