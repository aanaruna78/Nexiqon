"""HTTP API for tool-gateway. Contract: contracts/openapi/tool-gateway.json."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nexiqon_core.tenancy import TenantContext, require_current_context

# Routes reachable without a tenant context (rare; e.g. public metadata).
public_router = APIRouter(tags=["tool-gateway"])

# Every route here requires a verified tenant-context token.
tenant_router = APIRouter(prefix="/v1", tags=["tool-gateway"])


class ContextEcho(BaseModel):
    tenant_id: str
    actor_id: str
    actor_type: str


@tenant_router.get("/context", response_model=ContextEcho)
async def context(ctx: TenantContext = Depends(require_current_context)) -> ContextEcho:
    """Echo the verified tenant context (skeleton endpoint used by isolation smoke tests)."""
    return ContextEcho(
        tenant_id=str(ctx.tenant_id), actor_id=ctx.actor_id, actor_type=ctx.actor_type
    )
