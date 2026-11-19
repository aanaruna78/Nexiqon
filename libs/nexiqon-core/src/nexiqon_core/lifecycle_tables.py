"""A tenant lifecycle for services whose tenant data is a set of tenant-scoped tables.

Deletion runs with ``app.tenant_deletion = 'on'`` (append-only tables allow deletes only then),
in child-to-parent order, then counts again under RLS: the residue check passes only when every
table is empty for the tenant. Export returns each listed table's rows as JSON (secrets left out).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest

EXPORT_ROW_LIMIT = 50_000


def _plain(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _mine(model: type[Any], tenant_id: UUID) -> list[Any]:
    """An explicit tenant filter as well as RLS: some tables (outboxes) have no RLS at all."""
    column = getattr(model, "tenant_id", None)
    return [column == tenant_id] if column is not None else []


class TableLifecycle:
    def __init__(
        self,
        service: str,
        db: TenantSessionFactory,
        tables: Sequence[type[Any]],
        *,
        export: Sequence[type[Any]] = (),
        secret_columns: frozenset[str] = frozenset(),
        after_delete: Callable[[AsyncSession, UUID], Awaitable[dict[str, int]]] | None = None,
        residue: Callable[[AsyncSession, UUID], Awaitable[int]] | None = None,
    ) -> None:
        """``tables`` in deletion order (children first). ``after_delete``/``residue`` handle
        rows outside RLS (e.g. a tenant's own row in a global table)."""
        self.service = service
        self.db = db
        self.tables = list(tables)
        self.export_tables = list(export)
        self.secret_columns = secret_columns
        self.after_delete = after_delete
        self.residue = residue

    def _vars(self, tenant_id: UUID, deleting: bool = False) -> dict[str, str]:
        v = {"tenant_id": str(tenant_id), "actor_id": "service:governance"}
        if deleting:
            v["tenant_deletion"] = "on"
        return v

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        deleted: dict[str, int] = {}
        async with self.db.scoped(self._vars(tenant_id, deleting=True)) as s:
            for model in self.tables:
                result = await s.execute(delete(model).where(model.tenant_id == tenant_id))
                deleted[model.__tablename__] = int(result.rowcount or 0)  # type: ignore[attr-defined]
            if self.after_delete is not None:
                deleted.update(await self.after_delete(s, tenant_id))
        left = 0
        async with self.db.scoped(self._vars(tenant_id)) as s:
            for model in self.tables:
                left += int(
                    await s.scalar(
                        select(func.count()).select_from(model).where(*_mine(model, tenant_id))
                    )
                    or 0
                )
            if self.residue is not None:
                left += await self.residue(s, tenant_id)
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted=deleted,
            residue_check_passed=left == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        artifacts: list[dict[str, Any]] = []
        async with self.db.scoped(self._vars(tenant_id)) as s:
            for model in self.export_tables:
                columns = [c for c in model.__table__.columns if c.name not in self.secret_columns]
                rows = (
                    await s.execute(
                        select(*columns).where(*_mine(model, tenant_id)).limit(EXPORT_ROW_LIMIT)
                    )
                ).all()
                artifacts.append(
                    {
                        "kind": model.__tablename__,
                        "format": "json",
                        "rows": len(rows),
                        "data": [
                            {c.name: _plain(v) for c, v in zip(columns, r, strict=True)}
                            for r in rows
                        ],
                        "truncated": len(rows) == EXPORT_ROW_LIMIT,
                    }
                )
        return ExportManifest(service=self.service, tenant_id=tenant_id, artifacts=artifacts)
