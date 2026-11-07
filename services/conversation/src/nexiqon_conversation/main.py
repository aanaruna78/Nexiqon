"""Sessions, messages, provenance, feedback and escalations."""

from typing import Final

from fastapi import FastAPI

from nexiqon_conversation import __version__
from nexiqon_conversation.api import public_router, tenant_router
from nexiqon_conversation.lifecycle import lifecycle
from nexiqon_conversation.settings import ServiceSettings
from nexiqon_core.app import create_service_app

SERVICE_NAME: Final = "conversation"
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
