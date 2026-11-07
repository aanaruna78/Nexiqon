"""Config data model (schema ``config``). RLS and immutability trigger in migrations/versions/0001."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "config"
ENVIRONMENTS = ("dev", "staging", "prod")
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class ConfigObject(TenantScopedMixin, Base):
    __tablename__ = "config_objects"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "name"),)

    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(63))
    description: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[str] = mapped_column(String(200))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ConfigVersion(TenantScopedMixin, Base):
    """Drafts are editable; published versions are immutable (enforced by a DB trigger)."""

    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("object_id", "version"),)

    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.config_objects.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict[str, Any]] = mapped_column(_JSON)
    spec_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|published
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[str] = mapped_column(String(200))
    published_by: Mapped[str | None] = mapped_column(String(200), default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ConfigDeployment(TenantScopedMixin, Base):
    """Which published version of an object is live in an environment."""

    __tablename__ = "config_deployments"
    __table_args__ = (UniqueConstraint("object_id", "environment"),)

    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.config_objects.id", ondelete="CASCADE")
    )
    environment: Mapped[str] = mapped_column(String(16))
    version_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.config_versions.id"))
    version: Mapped[int] = mapped_column(Integer)
    deployed_by: Mapped[str] = mapped_column(String(200))


class DeploymentHistory(TenantScopedMixin, Base):
    __tablename__ = "deployment_history"

    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.config_objects.id", ondelete="CASCADE")
    )
    environment: Mapped[str] = mapped_column(String(16))
    from_version: Mapped[int | None] = mapped_column(Integer, default=None)
    to_version: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(500), default="")


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
