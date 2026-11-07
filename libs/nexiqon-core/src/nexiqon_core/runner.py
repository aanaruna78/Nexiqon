"""Deployment-group runner: serves several services from one process.

Each service package exposes ``create_app() -> FastAPI``. The runner mounts each under
``/<service>``, runs every mounted app's lifespan (Starlette does not do this for mounts), and
adds group-level ``/healthz`` and ``/readyz``.

    nexiqon-run --group control-core            # grouped deployment
    nexiqon-run --services identity             # one service (split deployment)
"""

from __future__ import annotations

import argparse
import importlib
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.routing import Mount

from nexiqon_core.app import run_readiness
from nexiqon_core.directory import Topology, module_for

AppFactory = Callable[[], FastAPI]


def load_factory(service: str) -> AppFactory:
    module = importlib.import_module(f"{module_for(service)}.main")
    return cast(AppFactory, module.create_app)


def build_group_app(
    name: str,
    services: Sequence[str],
    factories: dict[str, AppFactory] | None = None,
) -> FastAPI:
    """Compose services into one ASGI app. ``factories`` lets tests inject apps."""
    apps: dict[str, FastAPI] = {}
    for svc in services:
        factory = (factories or {}).get(svc) or load_factory(svc)
        apps[svc] = factory()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for sub in apps.values():
                await stack.enter_async_context(sub.router.lifespan_context(sub))
            yield

    group = FastAPI(title=f"nexiqon-group-{name}", lifespan=lifespan, openapi_url=None)

    @group.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "group": name, "services": sorted(apps)}

    @group.get("/readyz")
    async def readyz() -> JSONResponse:
        results = {
            svc: all((await run_readiness(a.state.readiness_checks)).values())
            for svc, a in apps.items()
        }
        ok = all(results.values())
        return JSONResponse(
            {"status": "ok" if ok else "unavailable", "services": results},
            status_code=200 if ok else 503,
        )

    for svc, sub in apps.items():
        group.router.routes.append(Mount(f"/{svc}", app=sub, name=svc))
    return group


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a Nexiqon deployment group")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--group", help="group name from the groups file")
    target.add_argument("--services", help="comma-separated services to run together")
    parser.add_argument("--groups-file", type=Path, default=Path("deploy/groups.yaml"))
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - containers bind all interfaces
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    topology = Topology.load(args.groups_file)
    if args.group:
        name, services = args.group, topology.groups[args.group].services
    else:
        services = tuple(s.strip() for s in args.services.split(",") if s.strip())
        name = "+".join(services)

    import uvicorn

    uvicorn.run(
        build_group_app(name, services),
        host=args.host,
        port=args.port or topology.port,
        log_config=None,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
