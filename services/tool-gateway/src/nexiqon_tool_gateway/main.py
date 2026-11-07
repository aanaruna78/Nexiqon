"""Policy-controlled tool execution with secrets, egress allowlist and approvals."""

from typing import Final

from fastapi import FastAPI

from nexiqon_core.app import create_service_app
from nexiqon_tool_gateway import __version__
from nexiqon_tool_gateway.api import public_router, tenant_router
from nexiqon_tool_gateway.lifecycle import lifecycle
from nexiqon_tool_gateway.settings import ServiceSettings

SERVICE_NAME: Final = "tool-gateway"
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
