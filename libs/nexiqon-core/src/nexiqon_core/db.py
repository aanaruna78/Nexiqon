"""Database access with Row-Level Security bound to the verified tenant context.

Every tenant-scoped table carries ``tenant_id`` and an RLS policy (see :func:`rls_policy_sql`).
Sessions opened through :class:`TenantSessionFactory` run inside a transaction that sets
``app.tenant_id`` with ``set_config(..., true)`` (transaction-local), so the setting can never
leak to another request through the connection pool. With no context set, policies match no rows.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.ids import uuid7
from nexiqon_core.tenancy import TenantContext

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class Base(DeclarativeBase):
    """Declarative base for service models."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class TenantScopedMixin(TimestampMixin):
    """Primary key + tenant id + timestamps. Tables using it MUST get an RLS policy."""

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(index=True, nullable=False)


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def rls_policy_sql(table: str, schema: str = "public") -> list[str]:
    """SQL statements enabling forced tenant isolation on ``schema.table``.

    Use from Alembic migrations: ``for stmt in rls_policy_sql("documents"): op.execute(stmt)``.
    """
    t = f"{_ident(schema)}.{_ident(table)}"
    predicate = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS tenant_isolation ON {t}",
        f"CREATE POLICY tenant_isolation ON {t} USING ({predicate}) WITH CHECK ({predicate})",
    ]


def create_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(url, echo=echo, pool_pre_ping=True)


class TenantSessionFactory:
    """Opens transactions scoped to one tenant context."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self, ctx: TenantContext) -> AsyncIterator[AsyncSession]:
        """Yield a session in a transaction bound to ``ctx``; commits on success."""
        async with self._sessions() as session, session.begin():
            await session.execute(
                text(
                    "SELECT set_config('app.tenant_id', :tid, true),"
                    " set_config('app.actor_id', :aid, true)"
                ),
                {"tid": str(ctx.tenant_id), "aid": ctx.actor_id},
            )
            yield session

    @asynccontextmanager
    async def system_session(self) -> AsyncIterator[AsyncSession]:
        """Session with no tenant context (RLS tables return nothing). For outbox relay etc."""
        async with self._sessions() as session, session.begin():
            yield session
