"""Email, webhook and in-app notifications."""

from typing import Final

from fastapi import FastAPI

from nexiqon_core.app import create_service_app
from nexiqon_notification import __version__
from nexiqon_notification.api import public_router, tenant_router
from nexiqon_notification.lifecycle import lifecycle
from nexiqon_notification.settings import ServiceSettings

SERVICE_NAME: Final = "notification"
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
