"""Tenant deletion/export for agent-runtime: threads, run traces and checkpoints."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from nexiqon_agent_runtime.models import Checkpoint, CheckpointBlob, CheckpointWrite, Run, Thread
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest, NoTenantData, TenantLifecycle

MODELS = (CheckpointWrite, CheckpointBlob, Checkpoint, Run, Thread)


class AgentLifecycle:
    def __init__(self, service: str, db: TenantSessionFactory) -> None:
        self.service = service
        self.db = db

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        variables = {"tenant_id": str(tenant_id), "tenant_deletion": "on"}
        deleted: dict[str, int] = {}
        async with self.db.scoped(variables) as s:
            for model in MODELS:
                result = await s.execute(delete(model).where(model.tenant_id == tenant_id))
                deleted[model.__tablename__] = int(result.rowcount or 0)  # type: ignore[attr-defined]
        async with self.db.scoped(variables) as s:
            left = sum(
                [int(await s.scalar(select(func.count()).select_from(m)) or 0) for m in MODELS]
            )
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted=deleted,
            residue_check_passed=left == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        # Conversations are exported by the conversation service; traces are operational data.
        return ExportManifest(service=self.service, tenant_id=tenant_id, artifacts=[])


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    return AgentLifecycle(service, db) if db is not None else NoTenantData(service)
