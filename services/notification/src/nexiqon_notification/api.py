"""HTTP API for notification. Contract: contracts/openapi/notification.json.

Email is sent only for platform services (``notification.email.send`` is service-only in the
policy), never directly for a browser: otherwise a public widget key would be an open mail relay.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy import func, select

from nexiqon_core.authz import require_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import NexiqonError, ServiceUnavailable
from nexiqon_core.events import add_event
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_notification.mail import Email, EmailSender
from nexiqon_notification.models import Delivery, Outbox

public_router = APIRouter(tags=["notification"])
tenant_router = APIRouter(prefix="/v1", tags=["notification"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
SOURCE = "nexiqon/notification"
# Deliberately simple: one @, no spaces or angle brackets, a dot in the domain.
ADDRESS = re.compile(r"^[^@\s<>,;\"]{1,64}@[^@\s<>,;\"]{1,253}\.[^@\s<>,;\"]{2,63}$")


class ContextEcho(BaseModel):
    tenant_id: str
    actor_id: str
    actor_type: str


@tenant_router.get("/context", response_model=ContextEcho)
async def context(ctx: Ctx) -> ContextEcho:
    """Echo the verified tenant context (used by isolation smoke tests)."""
    return ContextEcho(
        tenant_id=str(ctx.tenant_id), actor_id=ctx.actor_id, actor_type=ctx.actor_type
    )


class TooManyEmails(NexiqonError):
    status, code, title = 429, "too_many_emails", "Too many emails"


def valid_address(value: str) -> str:
    value = value.strip()
    if not ADDRESS.match(value):
        raise ValueError("not an email address")
    return value


def no_newlines(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("must be one line")
    return value


class EmailIn(BaseModel):
    to: Annotated[str, AfterValidator(valid_address)] = Field(max_length=320)
    subject: Annotated[str, AfterValidator(no_newlines)] = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200_000)
    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,62}$")
    reference: str | None = Field(default=None, max_length=200)


class DeliveryOut(BaseModel):
    id: str
    status: str


def recipient_hash(address: str) -> str:
    return hashlib.sha256(address.strip().lower().encode()).hexdigest()


@tenant_router.post(
    "/emails",
    response_model=DeliveryOut,
    status_code=202,
    dependencies=[require_permission("notification.email.send", "email")],
)
async def send_email(body: EmailIn, request: Request, ctx: Ctx) -> DeliveryOut:
    """Send one email for a platform service and log the delivery (without the address)."""
    db: TenantSessionFactory | None = request.app.state.db
    if db is None:
        raise ServiceUnavailable("Notification storage is not configured")
    sender: EmailSender = request.app.state.email
    settings = request.app.state.settings
    to_hash = recipient_hash(body.to)
    since = datetime.now(UTC) - timedelta(hours=1)
    sent = (Delivery.channel == "email", Delivery.status == "sent", Delivery.created_at > since)
    async with db.session(ctx) as s:
        recent = await s.scalar(select(func.count()).select_from(Delivery).where(*sent))
        to_one = await s.scalar(
            select(func.count())
            .select_from(Delivery)
            .where(*sent, Delivery.recipient_hash == to_hash)
        )
    if int(recent or 0) >= settings.max_emails_per_hour:
        raise TooManyEmails("This organization has sent too many emails in the last hour")
    if int(to_one or 0) >= settings.max_emails_per_recipient_per_hour:
        raise TooManyEmails("Too many emails to this address in the last hour")
    status, error = "sent", None
    try:
        await sender.send(Email(to=body.to, subject=body.subject, text=body.text))
    except Exception as exc:  # the relay's own message, never the address
        status, error = "failed", type(exc).__name__
    async with db.session(ctx) as s:
        d = Delivery(
            tenant_id=ctx.tenant_id,
            channel="email",
            kind=body.kind,
            reference=body.reference,
            recipient_hash=to_hash,
            requested_by=ctx.actor_id,
            status=status,
            error=error,
        )
        s.add(d)
        await s.flush()
        add_event(
            s,
            Outbox,
            ctx,
            source=SOURCE,
            type=f"nexiqon.notification.email.{status}",
            subject=body.kind,
            data={"delivery_id": str(d.id), "kind": body.kind, "reference": body.reference},
        )
        delivery_id = str(d.id)
    if status != "sent":
        raise ServiceUnavailable("The email could not be sent")
    return DeliveryOut(id=delivery_id, status=status)
