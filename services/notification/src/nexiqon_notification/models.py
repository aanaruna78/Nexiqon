"""notification data (schema ``notification``): the delivery log. Message bodies and addresses are
never stored: only a hash of the address, so a delivery can be traced without keeping the PII."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "notification"
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class Delivery(TenantScopedMixin, Base):
    __tablename__ = "deliveries"

    channel: Mapped[str] = mapped_column(String(16))  # email
    kind: Mapped[str] = mapped_column(String(63), index=True)  # e.g. conversation.transcript
    reference: Mapped[str | None] = mapped_column(String(200), default=None)
    recipient_hash: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))  # sent | failed | refused
    error: Mapped[str | None] = mapped_column(String(500), default=None)


class Webhook(TenantScopedMixin, Base):
    """An HTTPS endpoint of the tenant's that receives matching platform events, signed."""

    __tablename__ = "webhooks"

    url: Mapped[str] = mapped_column(String(2000))
    description: Mapped[str] = mapped_column(String(200), default="")
    # Event types (``conversation.escalated``) or prefixes (``evaluation.*``); empty = all.
    events: Mapped[list[str]] = mapped_column(_JSON, default=list)
    # The signing secret; shown once when created, never returned again.
    secret: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(200))
    failures: Mapped[int] = mapped_column(Integer, default=0)  # consecutive; disabled at the limit


class WebhookDelivery(TenantScopedMixin, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("webhook_id", "event_id"),)

    webhook_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.webhooks.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[UUID] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    # pending | delivered | failed (gave up)
    status: Mapped[str] = mapped_column(String(16), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )


class InboxItem(TenantScopedMixin, Base):
    """An in-app notification for everyone in the tenant holding one of ``roles``."""

    __tablename__ = "inbox_items"

    kind: Mapped[str] = mapped_column(String(63))  # message key in Studio
    roles: Mapped[list[str]] = mapped_column(_JSON, default=list)
    params: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    link: Mapped[str | None] = mapped_column(String(500), default=None)
    event_id: Mapped[UUID | None] = mapped_column(default=None)


class InboxRead(TenantScopedMixin, Base):
    __tablename__ = "inbox_reads"
    __table_args__ = (UniqueConstraint("item_id", "actor_id"),)

    item_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.inbox_items.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str] = mapped_column(String(200))


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
