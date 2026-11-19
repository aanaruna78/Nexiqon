"""metering data (schema ``metering``): read models built from platform events (MT-01, MT-02).

Nothing here is the source of truth: model-gateway's usage records, conversation's messages and
tool-gateway's call log are. These tables can be rebuilt by replaying events.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "metering"
_JSON = JSON().with_variant(JSONB(), "postgresql")
NO_AGENT = ""  # usage not tied to an assistant (indexing, previews)


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class Processed(TenantScopedMixin, Base):
    """Events already counted: redelivery never counts twice."""

    __tablename__ = "processed_events"
    __table_args__ = (UniqueConstraint("event_id"),)

    event_id: Mapped[UUID] = mapped_column()
    type: Mapped[str] = mapped_column(String(200))


class UsageDaily(TenantScopedMixin, Base):
    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint("tenant_id", "day", "agent", "operation", "profile", "provider", "model"),
    )

    day: Mapped[date] = mapped_column(Date, index=True)
    agent: Mapped[str] = mapped_column(String(63), default=NO_AGENT)
    operation: Mapped[str] = mapped_column(String(16))
    profile: Mapped[str] = mapped_column(String(63))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(200))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(16, 6), default=Decimal(0))


class ActivityDaily(TenantScopedMixin, Base):
    """Counters per day and assistant: turns, answered, unanswered, cited, escalations,
    feedback_up, feedback_down, tool_calls, tool_errors, conversations."""

    __tablename__ = "activity_daily"
    __table_args__ = (UniqueConstraint("tenant_id", "day", "agent", "metric"),)

    day: Mapped[date] = mapped_column(Date, index=True)
    agent: Mapped[str] = mapped_column(String(63), default=NO_AGENT)
    metric: Mapped[str] = mapped_column(String(32))
    value: Mapped[int] = mapped_column(Integer, default=0)


class ConversationFacts(TenantScopedMixin, Base):
    """One row per conversation, for the pack's KPIs (rates over conversations)."""

    __tablename__ = "conversation_facts"
    __table_args__ = (UniqueConstraint("tenant_id", "conversation_id"),)

    conversation_id: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(63), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)  # the day it started
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    rated_down: Mapped[bool] = mapped_column(Boolean, default=False)
    events: Mapped[list[str]] = mapped_column(_JSON, default=list)  # event kinds seen


class Budget(TenantScopedMixin, Base):
    """A monthly spend limit for the organization or one assistant, with alert thresholds."""

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("tenant_id", "agent"),)

    agent: Mapped[str] = mapped_column(String(63), default=NO_AGENT)  # "" = whole organization
    monthly_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    thresholds: Mapped[list[float]] = mapped_column(_JSON, default=lambda: [0.5, 0.8, 1.0])


class BudgetAlert(TenantScopedMixin, Base):
    __tablename__ = "budget_alerts"
    __table_args__ = (UniqueConstraint("budget_id", "month", "threshold"),)

    budget_id: Mapped[UUID] = mapped_column(index=True)
    agent: Mapped[str] = mapped_column(String(63), default=NO_AGENT)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    threshold: Mapped[float] = mapped_column(Numeric(4, 2))
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    extra: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
