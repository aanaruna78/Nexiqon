"""Channel adapters (web widget, API) and session bootstrap."""

from typing import Final

from fastapi import FastAPI

from nexiqon_channel import __version__
from nexiqon_channel.api import public_router, tenant_router
from nexiqon_channel.lifecycle import lifecycle
from nexiqon_channel.settings import ServiceSettings
from nexiqon_core.app import create_service_app

SERVICE_NAME: Final = "channel"
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
