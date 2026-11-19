"""Email, webhook and in-app notifications (NT-01: email first)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI
from sqlalchemy import text

from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer
from nexiqon_core.bus import Bus, EventRuntime
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_notification import __version__
from nexiqon_notification.api import public_router, tenant_router
from nexiqon_notification.lifecycle import lifecycle
from nexiqon_notification.mail import EmailSender, MemorySender
from nexiqon_notification.models import Outbox
from nexiqon_notification.settings import ServiceSettings

SERVICE_NAME: Final = "notification"
PLANE: Final = "control"


def _sender(settings: ServiceSettings) -> EmailSender:
    if settings.email.backend == "smtp":
        from nexiqon_notification.adapters.smtp import SmtpSender

        return SmtpSender(settings.email)
    return MemorySender()


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    bus: Bus | None = None,
    email: EmailSender | None = None,
) -> FastAPI:
    """Test seam: ``email`` (an in-memory sender)."""
    settings = settings or ServiceSettings()
    engine = (
        create_engine(
            settings.database.url.get_secret_value(), pool_size=settings.database.pool_size
        )
        if settings.database.url
        else None
    )
    db = TenantSessionFactory(engine) if engine else None
    sender = email or _sender(settings)
    events = None
    if settings.events.enabled and db is not None:
        events = EventRuntime(settings.events, SERVICE_NAME, bus)
        events.relay(db, Outbox)

    async def database_ready() -> bool:
        if engine is None:
            return False
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await sender.aclose()
        if engine is not None:
            await engine.dispose()

    checks: dict[str, Callable[[], Awaitable[bool]]] = (
        {"database": database_ready} if engine is not None else {}
    )
    app = create_service_app(
        name=SERVICE_NAME,
        version=__version__,
        plane=PLANE,
        settings=settings,
        routers=[public_router],
        tenant_routers=[tenant_router],
        lifecycle=lifecycle(SERVICE_NAME, db),
        readiness_checks=checks or None,
        lifespan=lifespan,
        authorizer=authorizer,
        events=events,
    )
    app.state.db = db
    app.state.email = sender
    return app
