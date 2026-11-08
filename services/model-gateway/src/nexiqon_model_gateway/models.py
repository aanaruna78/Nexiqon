"""Model gateway data (schema ``model_gateway``): usage records + outbox. RLS in migrations 0001."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "model_gateway"


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class UsageRecord(TenantScopedMixin, Base):
    """One provider call. Holds no prompt or completion text."""

    __tablename__ = "usage_records"

    actor_id: Mapped[str] = mapped_column(String(200))
    operation: Mapped[str] = mapped_column(String(16))  # chat | embed | rerank
    profile: Mapped[str] = mapped_column(String(63), index=True)
    requested_profile: Mapped[str] = mapped_column(String(63))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(200))
    classification: Mapped[str] = mapped_column(String(16))
    conversation_id: Mapped[str | None] = mapped_column(String(200), default=None, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal(0))
    priced: Mapped[bool] = mapped_column(Boolean, default=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
