"""CloudEvents envelope and the transactional outbox.

Services never publish directly to the bus inside a request. They add an :class:`OutboxEvent` in
the same DB transaction as the business write; :class:`OutboxRelay` publishes it afterwards.
The outbox table is service-internal infrastructure: it is NOT tenant-RLS protected because the
relay reads all tenants. Each event still carries its tenant id for consumers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from nexiqon_core.db import Base
from nexiqon_core.ids import uuid7
from nexiqon_core.tenancy import TenantContext

SPEC_VERSION = "1.0"
_JSON = JSON().with_variant(JSONB(), "postgresql")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    type: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(500), default=None)
    actor_id: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )

    def to_cloudevent(self) -> dict[str, Any]:
        event: dict[str, Any] = {
            "specversion": SPEC_VERSION,
            "id": str(self.id),
            "type": self.type,
            "source": self.source,
            "time": self.created_at.isoformat(),
            "datacontenttype": "application/json",
            "nexiqontenantid": str(self.tenant_id),
            "nexiqonactorid": self.actor_id,
            "data": self.data,
        }
        if self.subject:
            event["subject"] = self.subject
        return event


def add_event(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    source: str,
    type: str,
    data: dict[str, Any],
    subject: str | None = None,
) -> OutboxEvent:
    """Stage an event in the caller's transaction. Type format: ``nexiqon.<service>.<noun>.<verb>``."""
    if not type.startswith("nexiqon."):
        raise ValueError("event type must start with 'nexiqon.'")
    event = OutboxEvent(
        tenant_id=ctx.tenant_id,
        type=type,
        source=source,
        subject=subject,
        actor_id=ctx.actor_id,
        data=data,
    )
    session.add(event)
    return event


class EventPublisher(Protocol):
    """Event bus port. Adapters: NATS JetStream (default), in-memory (tests)."""

    async def publish(self, event: dict[str, Any]) -> None: ...


class InMemoryPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class OutboxRelay:
    """Publishes unpublished outbox rows in creation order. Safe to run in several replicas."""

    def __init__(self, publisher: EventPublisher, batch_size: int = 100) -> None:
        self._publisher = publisher
        self._batch = batch_size

    async def relay_once(self, session: AsyncSession) -> int:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(self._batch)
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        rows: Sequence[OutboxEvent] = (await session.execute(stmt)).scalars().all()
        for row in rows:
            await self._publisher.publish(row.to_cloudevent())
            row.published_at = datetime.now(UTC)
        return len(rows)
