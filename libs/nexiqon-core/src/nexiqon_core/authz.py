"""Authorization client used by every service (decisions are made by the authz service / OPA).

    @router.post("/members", dependencies=[require_permission("identity.members.write", "membership")])

Policy decides; services enforce. Neither configuration nor an LLM can grant access (ADR 0008).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

import httpx
from fastapi import Depends, Request
from pydantic import BaseModel, Field

from nexiqon_core.errors import Forbidden, Unauthorized
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext, require_current_context


class Resource(BaseModel):
    type: str
    id: str | None = None
    tenant_id: str | None = None  # defaults to the actor's tenant in policy
    attributes: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    allow: bool
    reasons: list[str] = Field(default_factory=list)


class Authorizer(Protocol):
    async def decide(
        self, ctx: TenantContext, token: str, action: str, resource: Resource
    ) -> Decision: ...


class HttpAuthorizer:
    """Calls ``POST {authz_url}/v1/decisions`` forwarding the caller's context token."""

    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def decide(
        self, ctx: TenantContext, token: str, action: str, resource: Resource
    ) -> Decision:
        response = await self._client.post(
            "/v1/decisions",
            headers={CONTEXT_HEADER: token},
            json={"action": action, "resource": resource.model_dump()},
        )
        if response.status_code != 200:
            # Fail closed: an unavailable or erroring authz service denies.
            return Decision(allow=False, reasons=[f"authz unavailable ({response.status_code})"])
        return Decision.model_validate(response.json())

    async def aclose(self) -> None:
        await self._client.aclose()


class StaticAuthorizer:
    """Role → permission-pattern table. For tests and single-node fallbacks only.

    Mirrors the semantics of the Rego policy: same tenant required; ``*`` matches within a
    segment, ``**`` across segments.
    """

    def __init__(self, roles: Mapping[str, list[str]]) -> None:
        self._roles = roles

    async def decide(
        self, ctx: TenantContext, token: str, action: str, resource: Resource
    ) -> Decision:
        if resource.tenant_id is not None and resource.tenant_id != str(ctx.tenant_id):
            return Decision(allow=False, reasons=["cross-tenant resource"])
        for role in sorted(ctx.roles):
            for pattern in self._roles.get(role, []):
                if _match(pattern, action):
                    return Decision(allow=True, reasons=[f"role {role} grants {pattern}"])
        return Decision(allow=False, reasons=["no matching permission"])


def _match(pattern: str, action: str) -> bool:
    """Glob with ``.`` as delimiter, like OPA ``glob.match(pattern, ["."], action)``."""
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^.]*")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.fullmatch("".join(parts), action) is not None


async def check_permission(request: Request, action: str, resource: Resource) -> Decision:
    """Imperative check for actions that depend on request data (e.g. a path parameter)."""
    ctx = getattr(request.state, "tenant_context", None)
    token = getattr(request.state, "context_token", None)
    if not isinstance(ctx, TenantContext) or token is None:
        raise Unauthorized("Missing tenant context")
    authorizer: Authorizer = request.app.state.authorizer
    decision = await authorizer.decide(ctx, token, action, resource)
    if not decision.allow:
        raise Forbidden(f"Not allowed: {action}")
    return decision


ResourceResolver = Callable[[Request], Awaitable[Resource] | Resource]


def require_permission(
    action: str, resource_type: str, *, resource: ResourceResolver | None = None
) -> Any:
    """FastAPI dependency: deny with 403 unless the authz decision allows ``action``."""

    async def dependency(
        request: Request, ctx: TenantContext = Depends(require_current_context)
    ) -> Decision:
        token = getattr(request.state, "context_token", None)
        if token is None:
            raise Unauthorized("Missing tenant context")
        res = Resource(type=resource_type)
        if resource is not None:
            produced = resource(request)
            res = produced if isinstance(produced, Resource) else await produced
        authorizer: Authorizer = request.app.state.authorizer
        decision = await authorizer.decide(ctx, token, action, res)
        if not decision.allow:
            raise Forbidden(f"Not allowed: {action}")
        return decision

    return Depends(dependency)
