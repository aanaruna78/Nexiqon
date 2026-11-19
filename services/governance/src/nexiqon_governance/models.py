"""governance data (schema ``governance``): tenant deletion/export requests and their per-service
steps (G-02), retention sweeps (G-01), and the registry of known tenants.

A completed deletion leaves only its request and steps: ids, service names, counts and times, no
personal data. That record is the deletion certificate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "governance"
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class LifecycleRequest(TenantScopedMixin, Base):
    __tablename__ = "lifecycle_requests"

    kind: Mapped[str] = mapped_column(String(16))  # delete | export
    # scheduled | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), index=True)
    requested_by: Mapped[str] = mapped_column(String(200))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    result_key: Mapped[str | None] = mapped_column(String(500), default=None)  # export archive
    error: Mapped[str | None] = mapped_column(String(1000), default=None)


class LifecycleStep(TenantScopedMixin, Base):
    __tablename__ = "lifecycle_steps"
    __table_args__ = (UniqueConstraint("request_id", "service"),)

    request_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.lifecycle_requests.id", ondelete="CASCADE"), index=True
    )
    service: Mapped[str] = mapped_column(String(63))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # pending | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Deletion: {"deleted": {...}, "residue_check_passed": bool}; export: {"artifacts": n, ...}
    detail: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class RetentionRun(TenantScopedMixin, Base):
    __tablename__ = "retention_runs"

    started_by: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))  # running | completed | failed
    policy: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    purged: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)  # service -> {kind: n}
    errors: Mapped[dict[str, str]] = mapped_column(_JSON, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class KnownTenant(Base):
    """Every tenant the platform has (from identity's events), for platform-wide sweeps. No
    RLS: it holds only ids, and only the governance worker reads it."""

    __tablename__ = "known_tenants"

    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
