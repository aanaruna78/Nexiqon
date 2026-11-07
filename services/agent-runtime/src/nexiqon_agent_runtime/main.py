"""Declarative LangGraph agent execution."""

from typing import Final

from fastapi import FastAPI

from nexiqon_agent_runtime import __version__
from nexiqon_agent_runtime.api import public_router, tenant_router
from nexiqon_agent_runtime.lifecycle import lifecycle
from nexiqon_agent_runtime.settings import ServiceSettings
from nexiqon_core.app import create_service_app

SERVICE_NAME: Final = "agent-runtime"
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
