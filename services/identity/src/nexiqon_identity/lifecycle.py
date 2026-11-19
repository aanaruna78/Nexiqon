"""Tenant deletion/export for identity: groups, keys, memberships and the organization itself.

People's accounts (users) are global and may belong to other organizations, so they stay; their
membership here goes. Identity runs last in a deletion saga: until then the organization exists.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import NoTenantData, TenantLifecycle
from nexiqon_core.lifecycle_tables import TableLifecycle
from nexiqon_identity.models import ApiKey, Group, GroupMember, Membership, Outbox, Tenant


async def _drop_tenant(s: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    result = await s.execute(delete(Tenant).where(Tenant.id == tenant_id))
    return {"tenants": int(result.rowcount or 0)}  # type: ignore[attr-defined]


async def _tenant_left(s: AsyncSession, tenant_id: UUID) -> int:
    return int(
        await s.scalar(select(func.count()).select_from(Tenant).where(Tenant.id == tenant_id)) or 0
    )


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    if db is None:
        return NoTenantData(service)
    return TableLifecycle(
        service,
        db,
        [GroupMember, Group, ApiKey, Membership, Outbox],
        export=[Tenant, Membership, Group, GroupMember, ApiKey],
        secret_columns=frozenset({"secret_hash"}),
        after_delete=_drop_tenant,
        residue=_tenant_left,
    )
