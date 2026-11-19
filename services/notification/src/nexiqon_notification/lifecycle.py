"""Tenant deletion/export for notification: the delivery log and outbox."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest, NoTenantData, TenantLifecycle
from nexiqon_notification.models import Delivery, Outbox


class NotificationLifecycle:
    def __init__(self, service: str, db: TenantSessionFactory) -> None:
        self.service = service
        self.db = db

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        variables = {"tenant_id": str(tenant_id), "tenant_deletion": "on"}
        deleted: dict[str, int] = {}
        async with self.db.scoped(variables) as s:
            for model in (Delivery, Outbox):
                result = await s.execute(delete(model).where(model.tenant_id == tenant_id))
                deleted[model.__tablename__] = int(result.rowcount or 0)  # type: ignore[attr-defined]
        async with self.db.scoped(variables) as s:
            left = int(await s.scalar(select(func.count()).select_from(Delivery)) or 0)
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted=deleted,
            residue_check_passed=left == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        async with self.db.scoped({"tenant_id": str(tenant_id)}) as s:
            rows = int(await s.scalar(select(func.count()).select_from(Delivery)) or 0)
        return ExportManifest(
            service=self.service,
            tenant_id=tenant_id,
            artifacts=[{"kind": "deliveries", "rows": rows, "format": "rows"}],
        )


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    return NotificationLifecycle(service, db) if db is not None else NoTenantData(service)
