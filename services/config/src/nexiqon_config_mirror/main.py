"""Configuration for a data plane that never waits on the control plane (DV-04).

Data-plane services read configuration from here exactly as they would from config:
``/v1/resolve/agents``, ``/v1/resolve/objects``, ``/v1/resolve/profiles``. Answers come from the
tenant's signed snapshot, pulled outbound from the control plane and verified (signature, digest,
tenant, environment), kept on disk, and served from there if the control plane is unreachable.
Only previews of unpublished versions are passed through, since drafts live in the control plane.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Final

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from nexiqon_config_mirror import __version__
from nexiqon_config_mirror.settings import ServiceSettings
from nexiqon_core.app import create_service_app
from nexiqon_core.authz import Authorizer, Resource, check_permission
from nexiqon_core.config_client import Snapshot, SnapshotClient
from nexiqon_core.errors import BadRequest, NexiqonError, NotFound, ServiceUnavailable
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext, require_current_context

SERVICE_NAME: Final = "config-mirror"
PLANE: Final = "data"
router = APIRouter(prefix="/v1", tags=["config-mirror"])
Ctx = Annotated[TenantContext, Depends(require_current_context)]


class FloorViolation(NexiqonError):
    status, code, title = 409, "security_floor_violation", "Security floor violated"


class Mirror:
    def __init__(
        self, settings: ServiceSettings, client: SnapshotClient, tokens: ServiceTokens
    ) -> None:
        self.settings = settings
        self.client = client
        self.tokens = tokens
        self._fresh: dict[uuid.UUID, tuple[float, Snapshot]] = {}

    async def snapshot(self, tenant: uuid.UUID) -> Snapshot:
        hit = self._fresh.get(tenant)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        snap = await self.client.get(self.tokens.for_tenant(tenant), str(tenant))
        self._fresh[tenant] = (time.monotonic() + self.settings.refresh_seconds, snap)
        return snap


def _mirror(request: Request) -> Mirror:
    mirror: Mirror = request.app.state.mirror
    return mirror


def _environment(request: Request, environment: str) -> None:
    if environment != request.app.state.settings.config_environment:
        raise BadRequest(
            f"This data plane serves the {request.app.state.settings.config_environment!r} environment"
        )


@router.get("/resolve/agents/{name}")
async def resolve_agent(
    name: str,
    request: Request,
    ctx: Ctx,
    environment: str = "prod",
    version: int | None = None,
) -> Any:
    await check_permission(request, "config.agent.read", Resource(type="agent", id=name))
    if version is not None:
        # A preview of an unpublished version: drafts live in the control plane only.
        return await _pass_through(
            request, f"/v1/resolve/agents/{name}", {"environment": environment, "version": version}
        )
    _environment(request, environment)
    snap = await _mirror(request).snapshot(ctx.tenant_id)
    agent = (snap.body.get("agents") or {}).get(name)
    if agent is None:
        raise NotFound(f"agent {name!r} is not deployed in {environment}")
    return agent


@router.get("/resolve/objects/{kind}/{name}")
async def resolve_object(
    kind: str, name: str, request: Request, ctx: Ctx, environment: str = "prod"
) -> dict[str, Any]:
    await check_permission(request, f"config.{kind}.read", Resource(type=kind, id=name))
    _environment(request, environment)
    snap = await _mirror(request).snapshot(ctx.tenant_id)
    for o in snap.body.get("objects") or []:
        if o["kind"] == kind and o["name"] == name:
            return {
                "kind": kind,
                "name": name,
                "environment": environment,
                "version": o["version"],
                "spec": o["spec"],
            }
    raise NotFound(f"{kind} {name!r} is not deployed in {environment}")


@router.get("/resolve/profiles/{kind}/{name}")
async def resolve_profile(
    kind: str, name: str, request: Request, ctx: Ctx, environment: str = "prod"
) -> dict[str, Any]:
    await check_permission(request, "config.profiles.resolve", Resource(type=kind, id=name))
    _environment(request, environment)
    snap = await _mirror(request).snapshot(ctx.tenant_id)
    found = ((snap.body.get("profiles") or {}).get(kind) or {}).get(name)
    if found is not None:
        profile: dict[str, Any] = found
        return profile
    blocked = ((snap.body.get("blocked_profiles") or {}).get(kind) or {}).get(name)
    if blocked is not None:
        error = FloorViolation("; ".join(blocked))
        error.errors = [{"message": m} for m in blocked]
        raise error
    raise NotFound(f"{kind} {name!r} is not deployed in {environment} and is not built in")


async def _pass_through(request: Request, path: str, params: dict[str, Any]) -> Any:
    token = str(request.state.context_token)
    try:
        r = await request.app.state.http.get(
            f"{request.app.state.settings.control_config_url.rstrip('/')}{path}",
            params=params,
            headers={CONTEXT_HEADER: token},
        )
    except httpx.HTTPError as exc:
        raise ServiceUnavailable("Previews need the control plane, which is unreachable") from exc
    return JSONResponse(r.json(), status_code=r.status_code)


@router.get("/mirror/status")
async def status(request: Request, ctx: Ctx) -> dict[str, Any]:
    """Which snapshot this data plane serves for the caller's tenant, and where it came from."""
    snap = await _mirror(request).snapshot(ctx.tenant_id)
    return {
        "environment": snap.environment,
        "digest": snap.digest,
        "source": snap.source,
        "agents": sorted(snap.body.get("agents") or {}),
        "objects": len(snap.body.get("objects") or []),
    }


def create_app(
    settings: ServiceSettings | None = None,
    *,
    authorizer: Authorizer | None = None,
    control_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Test seam: ``control_transport`` (the control plane's config service)."""
    settings = settings or ServiceSettings()
    client = SnapshotClient(
        settings.control_config_url,
        settings.config_environment,
        settings.snapshot_public_keys,
        settings.cache_dir,
        transport=control_transport,
    )
    http = httpx.AsyncClient(transport=control_transport, timeout=10.0, trust_env=False)
    tokens = ServiceTokens(SERVICE_NAME, settings.context_token, settings.mirror_identity)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()
        await http.aclose()

    app = create_service_app(
        name=SERVICE_NAME,
        version=__version__,
        plane=PLANE,
        settings=settings,
        tenant_routers=[router],
        lifespan=lifespan,
        authorizer=authorizer,
    )
    app.state.mirror = Mirror(settings, client, tokens)
    app.state.http = http
    return app
