"""notification data (schema ``notification``): the delivery log. Message bodies and addresses are
never stored: only a hash of the address, so a delivery can be traced without keeping the PII."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "notification"


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


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
