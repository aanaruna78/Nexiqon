"""Identity data model (schema ``identity``). RLS policies live in migrations/versions/0001."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, TimestampMixin, service_metadata
from nexiqon_core.events import OutboxMixin
from nexiqon_core.ids import uuid7

SCHEMA = "identity"
_JSON = JSON().with_variant(JSONB(), "postgresql")

ROLES = ("owner", "admin", "editor", "member")
KEY_ROLES = ("editor", "member", "end_user")  # API keys can never be owner/admin


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class Tenant(TimestampMixin, Base):
    """A customer organisation. RLS column is ``id`` (a tenant sees only itself)."""

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("idp_provider", "idp_org_ref"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(32), default="default")
    plan: Mapped[str] = mapped_column(String(32), default="trial")
    locale: Mapped[str] = mapped_column(String(16), default="en")
    status: Mapped[str] = mapped_column(String(16), default="active")
    deployment_mode: Mapped[str] = mapped_column(String(16), default="shared")
    idp_provider: Mapped[str | None] = mapped_column(String(64), default=None)
    idp_org_ref: Mapped[str | None] = mapped_column(String(200), default=None)


class User(TimestampMixin, Base):
    """A person, global across tenants. Visible only to themself and to tenants they belong to."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("idp_issuer", "idp_subject"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    idp_issuer: Mapped[str] = mapped_column(String(300))
    idp_subject: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), default=None, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Membership(TenantScopedMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        UniqueConstraint("tenant_id", "invited_email"),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), default=None, index=True
    )
    invited_email: Mapped[str | None] = mapped_column(String(320), default=None)
    role: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="active")  # invited|active|disabled
    invited_by: Mapped[str | None] = mapped_column(String(200), default=None)


class Group(TenantScopedMixin, Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")


class GroupMember(TenantScopedMixin, Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "membership_id"),)

    group_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.groups.id", ondelete="CASCADE"))
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.memberships.id", ondelete="CASCADE")
    )


class ApiKey(TenantScopedMixin, Base):
    """Server or widget key. Only a SHA-256 of the secret is stored."""

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))  # server|widget
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    roles: Mapped[list[str]] = mapped_column(_JSON, default=list)
    allowed_origins: Mapped[list[str]] = mapped_column(_JSON, default=list)
    agent_ids: Mapped[list[str]] = mapped_column(_JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_by: Mapped[str] = mapped_column(String(200))
    meta: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
