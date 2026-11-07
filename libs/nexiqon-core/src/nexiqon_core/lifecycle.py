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


class TenantLifecycle(Protocol):
    async def delete_tenant(self, tenant_id: UUID) -> DeletionReport: ...

    async def export_tenant(self, tenant_id: UUID) -> ExportManifest: ...


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
