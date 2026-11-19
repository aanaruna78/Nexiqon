"""Tenant lifecycle hooks every service implements (governance sagas call them).

Deletion and export of a tenant span all services, so each service must say what it holds and
remove or export it. The service template generates a stub; replace it when the service stores
tenant data.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel


class DeletionReport(BaseModel):
    service: str
    tenant_id: UUID
    deleted: dict[str, int]  # resource type -> count
    residue_check_passed: bool


class ExportManifest(BaseModel):
    service: str
    tenant_id: UUID
    artifacts: list[dict[str, Any]]  # e.g. {"kind": "documents", "uri": "s3://..."}


class RetentionPolicy(BaseModel):
    """How long a tenant keeps each kind of data (its default retention profile, G-01).
    A service purges only what is older than its own kind's limit; legal hold purges nothing."""

    conversations_days: int = 365
    traces_days: int = 30
    tool_results_days: int = 30
    legal_hold: bool = False


class RetentionReport(BaseModel):
    service: str
    tenant_id: UUID
    purged: dict[str, int]  # resource type -> count


class TenantLifecycle(Protocol):
    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport: ...

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest: ...


async def purge_expired(
    lifecycle: object, service: str, tenant_id: UUID, policy: RetentionPolicy
) -> RetentionReport:
    """Run a lifecycle's optional ``purge_expired(tenant_id, policy) -> dict[str, int]``."""
    purge = getattr(lifecycle, "purge_expired", None)
    if policy.legal_hold or purge is None:
        return RetentionReport(service=service, tenant_id=tenant_id, purged={})
    purged: dict[str, int] = await purge(tenant_id, policy)
    return RetentionReport(service=service, tenant_id=tenant_id, purged=purged)


class NoTenantData:
    """Lifecycle for services that store no tenant data yet."""

    def __init__(self, service: str) -> None:
        self.service = service

    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport:
        return DeletionReport(
            service=self.service, tenant_id=tenant_id, deleted={}, residue_check_passed=True
        )

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest:
        return ExportManifest(service=self.service, tenant_id=tenant_id, artifacts=[])
