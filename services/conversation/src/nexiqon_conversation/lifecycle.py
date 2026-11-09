"""Tenant deletion/export for conversation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from nexiqon_conversation.models import Conversation, Feedback, Message, Outbox
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import DeletionReport, ExportManifest, NoTenantData, TenantLifecycle


class ConversationLifecycle:
    def __init__(self, service: str, db: TenantSessionFactory) -> None:
        self.service = service
        self.db = db

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        variables = {"tenant_id": str(tenant_id), "tenant_deletion": "on"}
        deleted: dict[str, int] = {}
        async with self.db.scoped(variables) as s:
            for model in (Feedback, Message, Conversation, Outbox):
                result = await s.execute(delete(model).where(model.tenant_id == tenant_id))
                deleted[model.__tablename__] = int(result.rowcount or 0)  # type: ignore[attr-defined]
        async with self.db.scoped(variables) as s:
            left = sum(
                [
                    int(await s.scalar(select(func.count()).select_from(m)) or 0)
                    for m in (Feedback, Message, Conversation)
                ]
            )
        return DeletionReport(
            service=self.service,
            tenant_id=tenant_id,
            deleted=deleted,
            residue_check_passed=left == 0,
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        async with self.db.scoped({"tenant_id": str(tenant_id)}) as s:
            count = await s.scalar(select(func.count()).select_from(Conversation))
        return ExportManifest(
            service=self.service,
            tenant_id=tenant_id,
            artifacts=[{"kind": "conversations", "rows": int(count or 0), "format": "rows"}],
        )


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    return ConversationLifecycle(service, db) if db is not None else NoTenantData(service)
