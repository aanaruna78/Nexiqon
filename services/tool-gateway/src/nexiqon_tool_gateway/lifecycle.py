"""Tenant deletion/export for tool-gateway: call log, approvals, outbox (credentials: secrets store)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest, NoTenantData, TenantLifecycle
from nexiqon_tool_gateway.models import Approval, Outbox, ToolCall
from nexiqon_tool_gateway.secrets import Secrets


class ToolLifecycle:
    def __init__(self, service: str, db: TenantSessionFactory, secrets: Secrets) -> None:
        self.service = service
        self.db = db
        self.secrets = secrets

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        variables = {"tenant_id": str(tenant_id), "tenant_deletion": "on"}
        deleted: dict[str, int] = {}
        async with self.db.scoped(variables) as s:
            for model in (ToolCall, Approval, Outbox):
                result = await s.execute(delete(model).where(model.tenant_id == tenant_id))
                deleted[model.__tablename__] = int(result.rowcount or 0)  # type: ignore[attr-defined]
        names = await self.secrets.names(tenant_id)
        for name in names:
            await self.secrets.delete(tenant_id, name)
        deleted["credentials"] = len(names)
        async with self.db.scoped(variables) as s:
            left = sum(
                [
                    int(await s.scalar(select(func.count()).select_from(m)) or 0)
                    for m in (ToolCall, Approval)
                ]
            )
        left += len(await self.secrets.names(tenant_id))
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted=deleted,
            residue_check_passed=left == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        async with self.db.scoped({"tenant_id": str(tenant_id)}) as s:
            calls = await s.scalar(select(func.count()).select_from(ToolCall))
        return ExportManifest(
            service=self.service,
            tenant_id=tenant_id,
            artifacts=[{"kind": "tool_calls", "rows": int(calls or 0), "format": "rows"}],
        )


def lifecycle(service: str, db: TenantSessionFactory | None, secrets: Secrets) -> TenantLifecycle:
    return ToolLifecycle(service, db, secrets) if db is not None else NoTenantData(service)
