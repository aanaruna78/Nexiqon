"""Conversation data (schema ``conversation``): conversations, messages (with the answer contract),
feedback and outbox. Retention: each conversation carries ``retain_until`` from its agent's
retention profile; a sweep deletes expired ones (narrow RLS policy, see migration 0001)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "conversation"
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class Conversation(TenantScopedMixin, Base):
    __tablename__ = "conversations"

    agent: Mapped[str] = mapped_column(String(63))
    channel: Mapped[str] = mapped_column(String(32), default="api")
    locale: Mapped[str] = mapped_column(String(8), default="en")
    actor_id: Mapped[str] = mapped_column(String(200), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))
    # active | awaiting_input | awaiting_approval | escalated | closed
    status: Mapped[str] = mapped_column(String(24), default="active")
    title: Mapped[str | None] = mapped_column(String(200), default=None)
    handoff_summary: Mapped[str | None] = mapped_column(Text, default=None)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    retain_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )


class Message(TenantScopedMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # Answer contract for assistant messages: citations, abstained, kind, intent, route, run_id...
    contract: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    run_id: Mapped[UUID | None] = mapped_column(default=None)


class Feedback(TenantScopedMixin, Base):
    __tablename__ = "feedback"

    message_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.messages.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str] = mapped_column(String(200))
    rating: Mapped[str] = mapped_column(String(8))  # up | down
    comment: Mapped[str | None] = mapped_column(String(2000), default=None)


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
