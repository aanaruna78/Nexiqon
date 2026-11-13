"""HTTP API for channel. Contract: contracts/openapi/channel.json."""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from nexiqon_channel.channels import REGISTRY
from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.errors import Forbidden, NotFound, ServiceUnavailable
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext, require_current_context

public_router = APIRouter(tags=["channel"])
tenant_router = APIRouter(prefix="/v1", tags=["channel"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
NAME = r"^[a-z0-9][a-z0-9-]{1,62}$"


class ContextEcho(BaseModel):
    tenant_id: str
    actor_id: str
    actor_type: str


@tenant_router.get("/context", response_model=ContextEcho)
async def context(ctx: Ctx) -> ContextEcho:
    """Echo the verified tenant context (used by isolation smoke tests)."""
    return ContextEcho(
        tenant_id=str(ctx.tenant_id), actor_id=ctx.actor_id, actor_type=ctx.actor_type
    )


class Agents:
    """Resolved agents read with channel's own service identity, cached briefly per tenant."""

    def __init__(
        self,
        base_url: str | None,
        tokens: ServiceTokens,
        environment: str,
        ttl: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.tokens = tokens
        self.environment = environment
        self.ttl = ttl
        self.client = httpx.AsyncClient(transport=transport, timeout=10.0, trust_env=False)
        self._cache: dict[tuple[uuid.UUID, str], tuple[float, dict[str, Any]]] = {}

    async def get(self, tenant: uuid.UUID, agent: str) -> dict[str, Any]:
        hit = self._cache.get((tenant, agent))
        if hit and hit[0] > time.monotonic():
            return hit[1]
        if self.base is None:
            raise ServiceUnavailable("Config service URL is not configured")
        try:
            r = await self.client.get(
                f"{self.base}/v1/resolve/agents/{agent}",
                params={"environment": self.environment},
                headers={CONTEXT_HEADER: self.tokens.for_tenant(tenant)},
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Configuration is unreachable") from exc
        if r.status_code == 404:
            raise NotFound(f"Assistant {agent!r} is not available")
        if r.status_code >= 400:
            raise ServiceUnavailable(f"Configuration refused the request ({r.status_code})")
        resolved: dict[str, Any] = r.json()
        self._cache[(tenant, agent)] = (time.monotonic() + self.ttl, resolved)
        return resolved

    async def aclose(self) -> None:
        await self.client.aclose()


class ChannelInfo(BaseModel):
    name: str
    description: str


@tenant_router.get("/channels", response_model=list[ChannelInfo])
async def channels(request: Request, ctx: Ctx) -> list[ChannelInfo]:
    """Channel types this deployment offers."""
    await check_permission(request, "channel.settings.read", Resource(type="channel"))
    return [ChannelInfo(name=c.name, description=c.description) for c in REGISTRY.values()]


@tenant_router.get("/channels/{channel}/agents/{agent}")
async def channel_settings(
    channel: str,
    agent: Annotated[str, Field(pattern=NAME)],
    request: Request,
    response: Response,
    ctx: Ctx,
    locale: Annotated[str, Query(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")] = "en",
) -> dict[str, Any]:
    """What a client of this channel needs to talk to the agent: for the widget, its title,
    greeting, starter questions, theme colour and endpoints (W-00). Nothing secret: the full
    agent configuration never leaves the platform."""
    await check_permission(request, "channel.settings.read", Resource(type="agent", id=agent))
    adapter = REGISTRY.get(channel)
    if adapter is None:
        raise NotFound(f"Unknown channel {channel!r}")
    if ctx.actor_type == "widget" and channel != "widget":
        raise Forbidden("Widget keys can only use the widget channel")
    resolved = await request.app.state.agents.get(ctx.tenant_id, agent)
    response.headers["cache-control"] = "private, max-age=60"
    settings: dict[str, Any] = adapter.settings(resolved, locale.split("-")[0])
    return settings
