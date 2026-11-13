"""tool-gateway data (schema ``tool_gateway``): the call log, approvals, outbox. RLS in 0001.

Secrets are never stored here: credentials live in the secrets store (OpenBao) and the call log
keeps only the minimised result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "tool_gateway"
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class ToolCall(TenantScopedMixin, Base):
    __tablename__ = "tool_calls"
    __table_args__ = (UniqueConstraint("tenant_id", "tool", "idempotency_key"),)

    tool: Mapped[str] = mapped_column(String(63), index=True)
    tool_version: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String(63))
    actor_id: Mapped[str] = mapped_column(String(200), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(100), default=None)
    risk: Mapped[str] = mapped_column(String(8))
    # running | ok | error | refused
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64), default=None)
    http_status: Mapped[int | None] = mapped_column(Integer, default=None)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), default=None)
    args_hash: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(_JSON, default=None)
    approval_id: Mapped[UUID | None] = mapped_column(default=None)


class Approval(TenantScopedMixin, Base):
    """A confirmation the caller must give (write tools) or a task a person must approve."""

    __tablename__ = "approvals"

    tool: Mapped[str] = mapped_column(String(63), index=True)
    agent: Mapped[str] = mapped_column(String(63))
    kind: Mapped[str] = mapped_column(String(16))  # confirmation | human
    actor_id: Mapped[str] = mapped_column(String(200), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(100), default=None)
    arguments: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    args_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(1000))
    # pending | approved | declined | used | expired
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(200), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
