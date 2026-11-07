"""HTTP API for authz. Contract: contracts/openapi/authz.json."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from nexiqon_core.authz import Decision, Resource
from nexiqon_core.tenancy import TenantContext, require_current_context

public_router = APIRouter(tags=["authz"])
tenant_router = APIRouter(prefix="/v1", tags=["authz"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]


class DecisionRequest(BaseModel):
    action: str = Field(pattern=r"^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+){1,4}$")
    resource: Resource


def policy_input(ctx: TenantContext, body: DecisionRequest) -> dict[str, Any]:
    """The actor always comes from the verified context token, never from the request body."""
    return {
        "actor": {
            "tenant_id": str(ctx.tenant_id),
            "id": ctx.actor_id,
            "type": ctx.actor_type,
            "roles": sorted(ctx.roles),
            "groups": sorted(ctx.groups),
        },
        "action": body.action,
        "resource": body.resource.model_dump(exclude_none=True),
    }


@tenant_router.post("/decisions", response_model=Decision)
async def decide(body: DecisionRequest, ctx: Ctx, request: Request) -> Decision:
    """Evaluate whether the calling actor may perform ``action`` on ``resource``."""
    decision: Decision = await request.app.state.opa.evaluate(policy_input(ctx, body))
    return decision
