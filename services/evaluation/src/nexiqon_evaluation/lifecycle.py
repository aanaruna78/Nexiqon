"""Tenant deletion/export for evaluation: test sets, cases, runs, results, outbox."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest, NoTenantData, TenantLifecycle
from nexiqon_evaluation.models import EvalResult, EvalRun, EvalSet, EvalSetCase, Outbox

ORDER = (EvalResult, EvalRun, EvalSetCase, EvalSet, Outbox)


class EvaluationLifecycle:
    def __init__(self, service: str, db: TenantSessionFactory) -> None:
        self.service = service
        self.db = db

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        variables = {"tenant_id": str(tenant_id), "tenant_deletion": "on"}
        deleted: dict[str, int] = {}
        async with self.db.scoped(variables) as s:
            for model in ORDER:
                result = await s.execute(delete(model).where(model.tenant_id == tenant_id))
                deleted[model.__tablename__] = int(result.rowcount or 0)  # type: ignore[attr-defined]
        async with self.db.scoped(variables) as s:
            left = sum(
                [int(await s.scalar(select(func.count()).select_from(m)) or 0) for m in ORDER[:-1]]
            )
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted=deleted,
            residue_check_passed=left == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        async with self.db.scoped({"tenant_id": str(tenant_id)}) as s:
            counts = {
                m.__tablename__: int(await s.scalar(select(func.count()).select_from(m)) or 0)
                for m in (EvalSet, EvalSetCase, EvalRun, EvalResult)
            }
        return ExportManifest(
            service=self.service,
            tenant_id=tenant_id,
            artifacts=[{"kind": k, "rows": v, "format": "rows"} for k, v in counts.items()],
        )


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    return EvaluationLifecycle(service, db) if db is not None else NoTenantData(service)
