"""Tenant deletion/export for ingestion: records here, files in object storage."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from nexiqon_core.blobs import BlobStore
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest, NoTenantData, TenantLifecycle
from nexiqon_ingestion.models import Collection, Document, Outbox, Run, Source


class IngestionLifecycle:
    def __init__(self, service: str, db: TenantSessionFactory, blobs: BlobStore) -> None:
        self.service = service
        self.db = db
        self.blobs = blobs

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        variables = {"tenant_id": str(tenant_id), "tenant_deletion": "on"}
        async with self.db.scoped(variables) as s:
            keys = (
                await s.scalars(select(Document.blob_key).where(Document.blob_key.is_not(None)))
            ).all()
        for key in keys:
            if key:
                await self.blobs.delete(key)
        deleted: dict[str, int] = {}
        async with self.db.scoped(variables) as s:
            for model in (Document, Run, Source, Collection, Outbox):
                result = await s.execute(delete(model).where(model.tenant_id == tenant_id))
                deleted[model.__tablename__] = int(result.rowcount or 0)  # type: ignore[attr-defined]
        async with self.db.scoped(variables) as s:
            left = 0
            for model in (Document, Run, Source, Collection):
                left += int(await s.scalar(select(func.count()).select_from(model)) or 0)
        deleted["files"] = len([k for k in keys if k])
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted=deleted,
            residue_check_passed=left == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        async with self.db.scoped({"tenant_id": str(tenant_id)}) as s:
            rows = (
                await s.execute(
                    select(Document.uri, Document.blob_key, Document.media_type).where(
                        Document.blob_key.is_not(None), Document.status != "quarantined"
                    )
                )
            ).all()
        return ExportManifest(
            service=self.service,
            tenant_id=tenant_id,
            artifacts=[
                {"kind": "document", "uri": uri, "blob_key": key, "media_type": media}
                for uri, key, media in rows
            ],
        )


def lifecycle(
    service: str, db: TenantSessionFactory | None = None, blobs: BlobStore | None = None
) -> TenantLifecycle:
    return (
        IngestionLifecycle(service, db, blobs)
        if db is not None and blobs is not None
        else NoTenantData(service)
    )
