"""Tenant lifecycle endpoints every service has (G-01, G-02), for the governance service only.

``POST /v1/_lifecycle/{delete,export,retention}`` act on the tenant in the caller's context. They
accept only governance's own verified service identity (``service:governance``, ADR 0017) and
the service-only action ``governance.lifecycle.run``: no person, owner or API key can call them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.errors import Forbidden
from nexiqon_core.lifecycle import (
    DeletionReport,
    ExportManifest,
    RetentionPolicy,
    RetentionReport,
    purge_expired,
)
from nexiqon_core.tenancy import TenantContext, require_current_context

GOVERNANCE = "service:governance"
router = APIRouter(prefix="/v1/_lifecycle", tags=["lifecycle"], include_in_schema=False)
Ctx = Annotated[TenantContext, Depends(require_current_context)]


async def _governance_only(request: Request, ctx: TenantContext) -> None:
    if ctx.actor_type != "service" or ctx.actor_id != GOVERNANCE:
        raise Forbidden("Only the governance service manages a tenant's lifecycle")
    await check_permission(
        request, "governance.lifecycle.run", Resource(type="tenant", id=str(ctx.tenant_id))
    )


@router.post("/delete", response_model=DeletionReport)
async def delete(request: Request, ctx: Ctx) -> DeletionReport:
    """Remove everything this service holds for the tenant and confirm nothing is left."""
    await _governance_only(request, ctx)
    report: DeletionReport = await request.app.state.lifecycle.delete_tenant(ctx.tenant_id)
    return report


@router.post("/export", response_model=ExportManifest)
async def export(request: Request, ctx: Ctx) -> ExportManifest:
    """What this service holds for the tenant, for the tenant's export."""
    await _governance_only(request, ctx)
    manifest: ExportManifest = await request.app.state.lifecycle.export_tenant(ctx.tenant_id)
    return manifest


@router.post("/retention", response_model=RetentionReport)
async def retention(policy: RetentionPolicy, request: Request, ctx: Ctx) -> RetentionReport:
    """Purge what the tenant's retention policy says has expired."""
    await _governance_only(request, ctx)
    return await purge_expired(
        request.app.state.lifecycle, request.app.state.service_name, ctx.tenant_id, policy
    )
