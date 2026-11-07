"""Audit log (schema ``audit``): append-only, hash-chained per tenant."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata

SCHEMA = "audit"
GENESIS = "0" * 64
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class AuditEvent(TenantScopedMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("tenant_id", "seq"), UniqueConstraint("event_id"))

    seq: Mapped[int] = mapped_column(BigInteger)
    event_id: Mapped[UUID] = mapped_column()
    type: Mapped[str] = mapped_column(String(200), index=True)
    source: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(500), default=None)
    actor_id: Mapped[str] = mapped_column(String(200), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(_JSON)
    traceparent: Mapped[str | None] = mapped_column(String(64), default=None)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
