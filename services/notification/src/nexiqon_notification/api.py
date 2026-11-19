"""HTTP API for notification. Contract: contracts/openapi/notification.json.

Email is sent only for platform services (``notification.email.send`` is service-only in the
policy), never directly for a browser: otherwise a public widget key would be an open mail relay.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from nexiqon_core.authz import Resource, check_permission, require_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import BadRequest, NexiqonError, NotFound, ServiceUnavailable
from nexiqon_core.events import add_event
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_notification.mail import Email, EmailSender
from nexiqon_notification.models import (
    Delivery,
    InboxItem,
    InboxRead,
    Outbox,
    Webhook,
    WebhookDelivery,
)

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


# ===================================================================== webhooks (NT-01)


class WebhookIn(BaseModel):
    url: str = Field(max_length=2000, pattern=r"^https?://")
    description: str = Field(default="", max_length=200)
    events: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.*-]{1,120}$")]] = Field(
        default_factory=list, max_length=50
    )


class WebhookOut(BaseModel):
    id: uuid.UUID
    url: str
    description: str
    events: list[str]
    enabled: bool
    failures: int
    created_at: datetime


class WebhookCreated(WebhookOut):
    secret: str  # shown once


def _hook(h: Webhook) -> WebhookOut:
    return WebhookOut.model_validate(h, from_attributes=True)


def _db(request: Request) -> TenantSessionFactory:
    db: TenantSessionFactory | None = request.app.state.db
    if db is None:
        raise ServiceUnavailable("Notification storage is not configured")
    return db


async def _check_url(request: Request, url: str) -> None:
    try:
        await request.app.state.dispatcher.fetcher.check(url)
    except NexiqonError as exc:
        raise BadRequest(
            f"That address cannot receive webhooks: {exc.detail or exc.title}"
        ) from exc


@tenant_router.get("/webhooks", response_model=list[WebhookOut])
async def list_webhooks(request: Request, ctx: Ctx) -> list[WebhookOut]:
    await check_permission(request, "notification.webhooks.read", Resource(type="webhook"))
    async with _db(request).session(ctx) as s:
        return [_hook(h) for h in await s.scalars(select(Webhook).order_by(Webhook.created_at))]


@tenant_router.post("/webhooks", response_model=WebhookCreated, status_code=201)
async def create_webhook(body: WebhookIn, request: Request, ctx: Ctx) -> WebhookCreated:
    """Send matching events to your endpoint, signed with a secret shown only now."""
    await check_permission(request, "notification.webhooks.write", Resource(type="webhook"))
    await _check_url(request, body.url)
    secret = f"whsec_{secrets.token_urlsafe(32)}"
    async with _db(request).session(ctx) as s:
        h = Webhook(
            tenant_id=ctx.tenant_id,
            url=body.url,
            description=body.description,
            events=body.events,
            secret=secret,
            enabled=True,
            created_by=ctx.actor_id,
            failures=0,
        )
        s.add(h)
        await s.flush()
        await s.refresh(h)
        return WebhookCreated(**_hook(h).model_dump(), secret=secret)


class WebhookPatch(BaseModel):
    enabled: bool | None = None
    events: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.*-]{1,120}$")]] | None = None


@tenant_router.patch("/webhooks/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
    webhook_id: uuid.UUID, body: WebhookPatch, request: Request, ctx: Ctx
) -> WebhookOut:
    await check_permission(request, "notification.webhooks.write", Resource(type="webhook"))
    async with _db(request).session(ctx) as s:
        h = await s.get(Webhook, webhook_id)
        if h is None:
            raise NotFound("Webhook not found")
        if body.enabled is not None:
            h.enabled = body.enabled
            if body.enabled:
                h.failures = 0
        if body.events is not None:
            h.events = body.events
        await s.flush()
        return _hook(h)


@tenant_router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: uuid.UUID, request: Request, ctx: Ctx) -> Response:
    await check_permission(request, "notification.webhooks.write", Resource(type="webhook"))
    async with _db(request).session(ctx) as s:
        h = await s.get(Webhook, webhook_id)
        if h is None:
            raise NotFound("Webhook not found")
        await s.delete(h)
    return Response(status_code=204)


class DeliveryRow(BaseModel):
    id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    response_status: int | None
    error: str | None
    created_at: datetime
    next_attempt_at: datetime | None


@tenant_router.get("/webhooks/{webhook_id}/deliveries", response_model=list[DeliveryRow])
async def deliveries(webhook_id: uuid.UUID, request: Request, ctx: Ctx) -> list[DeliveryRow]:
    await check_permission(request, "notification.webhooks.read", Resource(type="webhook"))
    async with _db(request).session(ctx) as s:
        rows = await s.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(50)
        )
        return [DeliveryRow.model_validate(r, from_attributes=True) for r in rows]


@tenant_router.post("/webhooks/{webhook_id}/test", response_model=DeliveryRow)
async def test_webhook(webhook_id: uuid.UUID, request: Request, ctx: Ctx) -> DeliveryRow:
    """Send a ``notification.webhook.test`` event now and report what the endpoint answered."""
    await check_permission(request, "notification.webhooks.write", Resource(type="webhook"))
    event_id = uuid.uuid4()
    event = {
        "specversion": "1.0",
        "id": str(event_id),
        "type": "nexiqon.notification.webhook.test",
        "source": SOURCE,
        "time": datetime.now(UTC).isoformat(),
        "nexiqontenantid": str(ctx.tenant_id),
        "data": {"webhook_id": str(webhook_id)},
    }
    async with _db(request).session(ctx) as s:
        if await s.get(Webhook, webhook_id) is None:
            raise NotFound("Webhook not found")
        await s.execute(
            insert(WebhookDelivery).values(
                id=event_id,
                tenant_id=ctx.tenant_id,
                webhook_id=webhook_id,
                event_id=event_id,
                event_type=event["type"],
                payload=event,
                status="pending",
                attempts=0,
                next_attempt_at=datetime.now(UTC),
            )
        )
    await request.app.state.dispatcher.attempt(ctx.tenant_id, event_id)
    async with _db(request).session(ctx) as s:
        d = await s.get(WebhookDelivery, event_id)
        assert d is not None
        return DeliveryRow.model_validate(d, from_attributes=True)


# ===================================================================== in-app inbox (NT-01)


class InboxOut(BaseModel):
    id: uuid.UUID
    kind: str
    params: dict[str, object]
    link: str | None
    created_at: datetime
    read: bool


class Inbox(BaseModel):
    unread: int
    items: list[InboxOut]


async def _visible(s: object, ctx: TenantContext) -> list[InboxItem]:
    rows = await s.scalars(  # type: ignore[attr-defined]
        select(InboxItem).order_by(InboxItem.created_at.desc()).limit(200)
    )
    return [i for i in rows if set(i.roles or []) & set(ctx.roles)][:50]


@tenant_router.get("/inbox", response_model=Inbox)
async def inbox(request: Request, ctx: Ctx) -> Inbox:
    """What needs your attention, for your roles in this organization."""
    await check_permission(request, "notification.inbox.read", Resource(type="inbox"))
    async with _db(request).session(ctx) as s:
        items = await _visible(s, ctx)
        read = set(
            await s.scalars(
                select(InboxRead.item_id).where(
                    InboxRead.actor_id == ctx.actor_id, InboxRead.item_id.in_([i.id for i in items])
                )
            )
        )
    out = [
        InboxOut(
            id=i.id,
            kind=i.kind,
            params=i.params,
            link=i.link,
            created_at=i.created_at,
            read=i.id in read,
        )
        for i in items
    ]
    return Inbox(unread=sum(not o.read for o in out), items=out)


class ReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)  # empty = everything


@tenant_router.post("/inbox/read", response_model=Inbox)
async def mark_read(body: ReadIn, request: Request, ctx: Ctx) -> Inbox:
    await check_permission(request, "notification.inbox.read", Resource(type="inbox"))
    async with _db(request).session(ctx) as s:
        visible = {i.id for i in await _visible(s, ctx)}
        for item_id in body.ids or visible:
            if item_id in visible:
                await s.execute(
                    insert(InboxRead)
                    .values(
                        id=uuid.uuid4(),
                        tenant_id=ctx.tenant_id,
                        item_id=item_id,
                        actor_id=ctx.actor_id,
                    )
                    .on_conflict_do_nothing(index_elements=["item_id", "actor_id"])
                )
    return await inbox(request, ctx)
