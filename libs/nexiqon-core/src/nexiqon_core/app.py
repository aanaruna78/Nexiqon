"""Service application factory: every service is built through :func:`create_service_app`."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from nexiqon_core.authz import Authorizer, HttpAuthorizer
from nexiqon_core.directory import Topology
from nexiqon_core.errors import install_error_handlers
from nexiqon_core.lifecycle import NoTenantData, TenantLifecycle
from nexiqon_core.logging import configure_logging
from nexiqon_core.settings import CoreSettings
from nexiqon_core.telemetry import configure_telemetry
from nexiqon_core.tenancy import ContextTokenVerifier, tenant_context_dependency

Plane = Literal["control", "data"]
ReadinessCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]
REQUEST_ID_HEADER = "X-Request-ID"


def create_service_app(
    *,
    name: str,
    version: str,
    plane: Plane,
    settings: CoreSettings | None = None,
    routers: Sequence[APIRouter] = (),
    tenant_routers: Sequence[APIRouter] = (),
    readiness_checks: dict[str, ReadinessCheck] | None = None,
    lifecycle: TenantLifecycle | None = None,
    lifespan: Lifespan | None = None,
    authorizer: Authorizer | None = None,
) -> FastAPI:
    """Build a FastAPI app with the chassis wired in.

    ``routers`` are reachable without a tenant context (each such route must be deliberate:
    the isolation harness lists them); ``tenant_routers`` require a verified tenant-context token
    on every route. ``authorizer`` defaults to the authz service resolved from the topology.
    """
    settings = settings or CoreSettings(service_name=name)
    configure_logging(name, settings.log_level, settings.log_json)
    checks = dict(readiness_checks or {})

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        log = structlog.get_logger().bind(service=name)
        log.info("service_starting", version=version, plane=plane)
        try:
            if lifespan is not None:
                async with lifespan(app):
                    yield
            else:
                yield
        finally:
            closer = getattr(app.state.authorizer, "aclose", None)
            if closer is not None:
                await closer()
            log.info("service_stopped")

    app = FastAPI(title=f"nexiqon-{name}", version=version, lifespan=_lifespan)
    app.state.settings = settings
    app.state.service_name = name
    app.state.plane = plane
    app.state.lifecycle = lifecycle or NoTenantData(name)
    app.state.readiness_checks = checks
    app.state.authorizer = authorizer or _default_authorizer(settings)
    install_error_handlers(app)

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid, service=name)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "service")
        response.headers[REQUEST_ID_HEADER] = rid
        return response

    @app.get("/healthz", tags=["ops"], include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": name}

    @app.get("/readyz", tags=["ops"], include_in_schema=False)
    async def readyz() -> JSONResponse:
        results = await run_readiness(checks)
        ok = all(results.values())
        body: dict[str, Any] = {"status": "ok" if ok else "unavailable", "checks": results}
        return JSONResponse(body, status_code=200 if ok else 503)

    @app.get("/meta", tags=["ops"])
    async def meta() -> dict[str, str]:
        return {"service": name, "version": version, "plane": plane}

    public_paths: set[str] = {"/healthz", "/readyz", "/meta"}
    for router in routers:
        app.include_router(router)
        public_paths.update(r.path for r in router.routes if isinstance(r, APIRoute))
    if tenant_routers:
        dep = tenant_context_dependency(ContextTokenVerifier(settings.context_token))
        for router in tenant_routers:
            app.include_router(router, dependencies=[Depends(dep)])
    app.state.public_paths = frozenset(public_paths)

    configure_telemetry(app, name, version, settings.telemetry)
    return app


async def run_readiness(checks: dict[str, ReadinessCheck]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for check_name, check in checks.items():
        try:
            results[check_name] = await check()
        except Exception:  # a failing check means "not ready", never a crash
            results[check_name] = False
    return results


def _default_authorizer(settings: CoreSettings) -> Authorizer:
    url = settings.authz_url
    if url is None:
        try:
            url = Topology.load(settings.groups_file).url_for("authz")
        except (OSError, KeyError):
            url = "http://authz:8000/authz"
    return HttpAuthorizer(url)
