"""Tenant deletion/export for model-gateway: usage records and outbox rows (no prompt text)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest, NoTenantData, TenantLifecycle
from nexiqon_model_gateway.models import Outbox, UsageRecord


class UsageLifecycle:
    def __init__(self, service: str, db: TenantSessionFactory) -> None:
        self.service = service
        self.db = db

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        variables = {"tenant_id": str(tenant_id), "tenant_deletion": "on"}
        async with self.db.scoped(variables) as s:
            usage = await s.execute(delete(UsageRecord).where(UsageRecord.tenant_id == tenant_id))
            outbox = await s.execute(delete(Outbox).where(Outbox.tenant_id == tenant_id))
        async with self.db.scoped(variables) as s:
            left = await s.scalar(
                select(func.count())
                .select_from(UsageRecord)
                .where(UsageRecord.tenant_id == tenant_id)
            )
            left_outbox = await s.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.tenant_id == tenant_id)
            )
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted={
                "usage_records": usage.rowcount,  # type: ignore[attr-defined]
                "outbox_events": outbox.rowcount,  # type: ignore[attr-defined]
            },
            residue_check_passed=(left or 0) == 0 and (left_outbox or 0) == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        async with self.db.scoped({"tenant_id": str(tenant_id)}) as s:
            count = await s.scalar(
                select(func.count())
                .select_from(UsageRecord)
                .where(UsageRecord.tenant_id == tenant_id)
            )
        return ExportManifest(
            service=self.service,
            tenant_id=tenant_id,
            artifacts=[{"kind": "usage_records", "rows": int(count or 0), "format": "rows"}],
        )


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    return UsageLifecycle(service, db) if db is not None else NoTenantData(service)
