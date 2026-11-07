"""Test sets, evaluation runs, scorecards and release gates."""

from typing import Final

from fastapi import FastAPI

from nexiqon_core.app import create_service_app
from nexiqon_evaluation import __version__
from nexiqon_evaluation.api import public_router, tenant_router
from nexiqon_evaluation.lifecycle import lifecycle
from nexiqon_evaluation.settings import ServiceSettings

SERVICE_NAME: Final = "evaluation"
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
