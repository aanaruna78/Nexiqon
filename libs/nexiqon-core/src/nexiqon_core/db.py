"""Database access with Row-Level Security bound to the verified tenant context.

Every tenant-scoped table carries ``tenant_id`` and an RLS policy (see :func:`rls_policy_sql`).
Sessions opened through :class:`TenantSessionFactory` run inside a transaction that sets
``app.tenant_id`` (and any extra ``app.*`` variables) with ``set_config(..., true)``, which is
transaction-local, so a setting can never leak to another request through the connection pool.
With no context set, tenant policies match no rows.

Each service owns one PostgreSQL schema: see :func:`service_metadata`.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, MetaData, func, text
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
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base in the default schema (tests and tools only; services use make_base)."""

    metadata = MetaData(naming_convention=NAMING)


def service_metadata(schema: str) -> MetaData:
    """Metadata for a service's own schema. Each service declares its own base::

        class Base(DeclarativeBase):
            metadata = service_metadata("identity")

    Separate registries let several services share one process (deployment groups).
    """
    return MetaData(schema=_ident(schema), naming_convention=NAMING)


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


def setting(name: str, cast: str = "uuid") -> str:
    """SQL expression reading a transaction-local ``app.<name>`` variable (NULL when unset)."""
    return f"nullif(current_setting('app.{_ident(name)}', true), '')::{cast}"


def rls_policy_sql(table: str, schema: str = "public", column: str = "tenant_id") -> list[str]:
    """SQL statements enabling forced tenant isolation on ``schema.table``.

    Use from Alembic migrations: ``for stmt in rls_policy_sql("documents", "knowledge"): op.execute(stmt)``.
    """
    t = f"{_ident(schema)}.{_ident(table)}"
    predicate = f"{_ident(column)} = {setting('tenant_id')}"
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS tenant_isolation ON {t}",
        f"CREATE POLICY tenant_isolation ON {t} USING ({predicate}) WITH CHECK ({predicate})",
    ]


def extra_policy_sql(
    table: str,
    schema: str,
    name: str,
    using: str,
    *,
    command: str = "ALL",
    with_check: str | None = None,
) -> list[str]:
    """An additional permissive policy (e.g. a user reading their own rows across tenants).

    Permissive policies are OR-ed with ``tenant_isolation``. Keep predicates narrow and bound to
    transaction-local ``app.*`` variables set by trusted code, never by request input directly.
    """
    t = f"{_ident(schema)}.{_ident(table)}"
    if command not in {"ALL", "SELECT", "INSERT", "UPDATE", "DELETE"}:
        raise ValueError(f"bad policy command {command!r}")
    sql = f"CREATE POLICY {_ident(name)} ON {t} FOR {command}"
    if command != "INSERT":
        sql += f" USING ({using})"
    if with_check is not None and command in {"ALL", "INSERT", "UPDATE"}:
        sql += f" WITH CHECK ({with_check})"
    return [f"DROP POLICY IF EXISTS {_ident(name)} ON {t}", sql]


async def set_variables(session: AsyncSession, **variables: str) -> None:
    """Set transaction-local ``app.<name>`` variables inside an open transaction."""
    for key, value in variables.items():
        await session.execute(
            text("SELECT set_config(:k, :v, true)"), {"k": f"app.{_ident(key)}", "v": value}
        )


def create_engine(url: str, *, echo: bool = False, pool_size: int = 5) -> AsyncEngine:
    return create_async_engine(url, echo=echo, pool_pre_ping=True, pool_size=pool_size)


class TenantSessionFactory:
    """Opens transactions with RLS variables bound."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def scoped(self, variables: Mapping[str, str]) -> AsyncIterator[AsyncSession]:
        """Session in a transaction with ``app.<key>`` set for each item; commits on success."""
        async with self._sessions() as session, session.begin():
            await set_variables(session, **variables)
            yield session

    @asynccontextmanager
    async def session(self, ctx: TenantContext, **extra: str) -> AsyncIterator[AsyncSession]:
        """Session bound to ``ctx`` (tenant + actor), plus optional extra variables."""
        variables = {"tenant_id": str(ctx.tenant_id), "actor_id": ctx.actor_id, **extra}
        async with self.scoped(variables) as session:
            yield session

    @asynccontextmanager
    async def system_session(self) -> AsyncIterator[AsyncSession]:
        """Session with no tenant context (RLS tables return nothing). For outbox relay etc."""
        async with self.scoped({}) as session:
            yield session
