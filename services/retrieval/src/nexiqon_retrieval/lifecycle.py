"""Tenant deletion/export for retrieval: the index (rebuilt from ingestion, so export is a count)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest, NoTenantData, TenantLifecycle
from nexiqon_retrieval.models import IndexNode


class IndexLifecycle:
    def __init__(self, service: str, db: TenantSessionFactory) -> None:
        self.service = service
        self.db = db

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        variables = {"tenant_id": str(tenant_id), "tenant_deletion": "on"}
        async with self.db.scoped(variables) as s:
            result = await s.execute(delete(IndexNode).where(IndexNode.tenant_id == tenant_id))
        async with self.db.scoped(variables) as s:
            left = await s.scalar(select(func.count()).select_from(IndexNode))
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted={"index_nodes": int(result.rowcount or 0)},  # type: ignore[attr-defined]
            residue_check_passed=(left or 0) == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        # The index is derived data: an export carries the source documents (ingestion), not vectors.
        return ExportManifest(service=self.service, tenant_id=tenant_id, artifacts=[])


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    return IndexLifecycle(service, db) if db is not None else NoTenantData(service)
