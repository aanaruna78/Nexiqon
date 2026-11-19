"""HTTP API for governance (G-01, G-02). Contract: contracts/openapi/governance.json.

* delete the organization (owner only, typed confirmation, a grace period it can be cancelled in)
* export everything it holds (owner only) as one archive
* follow either one service by service
* see and start retention sweeps (admins)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import BadRequest, Conflict, NotFound, ServiceUnavailable
from nexiqon_core.events import add_event
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_core.workflows import TenantScope, workflow_id
from nexiqon_governance.models import LifecycleRequest, LifecycleStep, Outbox, RetentionRun
from nexiqon_governance.runner import remember_tenant

public_router = APIRouter(tags=["governance"])
tenant_router = APIRouter(prefix="/v1", tags=["governance"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
SOURCE = "nexiqon/governance"


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


def _db(request: Request) -> TenantSessionFactory:
    db: TenantSessionFactory | None = request.app.state.db
    if db is None:
        raise ServiceUnavailable("Governance storage is not configured")
    return db


def _temporal(request: Request) -> object:
    temporal = request.app.state.temporal
    if temporal is None:
        raise ServiceUnavailable("Lifecycle requests need the workflow engine")
    return temporal


class StepOut(BaseModel):
    service: str
    position: int
    status: str
    attempts: int
    detail: dict[str, object]
    finished_at: datetime | None


class RequestOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    requested_by: str
    run_after: datetime
    created_at: datetime
    finished_at: datetime | None
    downloadable: bool
    error: str | None
    steps: list[StepOut] = Field(default_factory=list)


async def _out(s: object, r: LifecycleRequest, with_steps: bool = True) -> RequestOut:
    steps: list[StepOut] = []
    if with_steps:
        rows = await s.scalars(  # type: ignore[attr-defined]
            select(LifecycleStep)
            .where(LifecycleStep.request_id == r.id)
            .order_by(LifecycleStep.position)
        )
        steps = [StepOut.model_validate(x, from_attributes=True) for x in rows]
    return RequestOut(
        id=r.id,
        kind=r.kind,
        status=r.status,
        requested_by=r.requested_by,
        run_after=r.run_after,
        created_at=r.created_at,
        finished_at=r.finished_at,
        downloadable=bool(r.result_key),
        error=r.error,
        steps=steps,
    )


class DeleteIn(BaseModel):
    # The organization's id, which Studio fills in only after the owner types its address.
    confirm: uuid.UUID


async def _start(
    request: Request, ctx: TenantContext, kind: Literal["delete", "export"], grace: float
) -> RequestOut:
    temporal = _temporal(request)
    settings = request.app.state.settings
    await remember_tenant(_db(request), ctx.tenant_id)
    async with _db(request).session(ctx) as s:
        busy = await s.scalar(
            select(LifecycleRequest.id).where(
                LifecycleRequest.kind == kind, LifecycleRequest.status.in_(["scheduled", "running"])
            )
        )
        if busy is not None:
            raise Conflict(f"A {kind} request is already in progress")
        req = LifecycleRequest(
            tenant_id=ctx.tenant_id,
            kind=kind,
            status="scheduled",
            requested_by=ctx.actor_id,
            run_after=datetime.now(UTC) + timedelta(seconds=grace),
        )
        s.add(req)
        await s.flush()
        add_event(
            s,
            Outbox,
            ctx,
            source=SOURCE,
            type=f"nexiqon.governance.tenant.{kind}.requested",
            subject=f"request/{req.id}",
            data={"request_id": str(req.id), "run_after": req.run_after.isoformat()},
        )
        out = await _out(s, req, with_steps=False)
    scope = TenantScope.of(ctx)
    await temporal.start_workflow(  # type: ignore[attr-defined]
        "governance.TenantRequest",
        args=[scope, str(out.id), kind, grace],
        id=workflow_id(scope, f"tenant-{kind}", str(out.id)),
        task_queue=settings.task_queue,
    )
    return out


@tenant_router.post("/lifecycle/delete", response_model=RequestOut, status_code=202)
async def request_deletion(body: DeleteIn, request: Request, ctx: Ctx) -> RequestOut:
    """Delete the whole organization: every assistant, document, conversation and setting, in
    every service. Owner only; runs after the grace period unless cancelled."""
    await check_permission(request, "governance.tenant.delete", Resource(type="tenant"))
    if body.confirm != ctx.tenant_id:
        raise BadRequest("The confirmation does not match this organization")
    grace = float(request.app.state.settings.deletion_grace_hours) * 3600
    return await _start(request, ctx, "delete", grace)


@tenant_router.post("/lifecycle/export", response_model=RequestOut, status_code=202)
async def request_export(request: Request, ctx: Ctx) -> RequestOut:
    """Export everything the organization holds, from every service, as one archive."""
    await check_permission(request, "governance.tenant.export", Resource(type="tenant"))
    return await _start(request, ctx, "export", 0)


@tenant_router.get("/lifecycle/requests", response_model=list[RequestOut])
async def list_requests(request: Request, ctx: Ctx) -> list[RequestOut]:
    await check_permission(request, "governance.requests.read", Resource(type="tenant"))
    async with _db(request).session(ctx) as s:
        rows = await s.scalars(
            select(LifecycleRequest).order_by(LifecycleRequest.created_at.desc()).limit(20)
        )
        return [await _out(s, r) for r in rows]


@tenant_router.get("/lifecycle/requests/{request_id}", response_model=RequestOut)
async def get_request(request_id: uuid.UUID, request: Request, ctx: Ctx) -> RequestOut:
    await check_permission(request, "governance.requests.read", Resource(type="tenant"))
    async with _db(request).session(ctx) as s:
        r = await s.get(LifecycleRequest, request_id)
        if r is None:
            raise NotFound("Request not found")
        return await _out(s, r)


@tenant_router.post("/lifecycle/requests/{request_id}/cancel", response_model=RequestOut)
async def cancel_request(request_id: uuid.UUID, request: Request, ctx: Ctx) -> RequestOut:
    """Stop a scheduled deletion during its grace period."""
    await check_permission(request, "governance.tenant.delete", Resource(type="tenant"))
    async with _db(request).session(ctx) as s:
        r = await s.get(LifecycleRequest, request_id)
        if r is None:
            raise NotFound("Request not found")
        if r.kind != "delete" or r.status != "scheduled":
            raise Conflict("Only a scheduled deletion can be cancelled")
    handle = _temporal(request).get_workflow_handle(  # type: ignore[attr-defined]
        workflow_id(TenantScope.of(ctx), "tenant-delete", str(request_id))
    )
    await handle.signal("cancel")
    await handle.result()
    async with _db(request).session(ctx) as s:
        r = await s.get(LifecycleRequest, request_id)
        assert r is not None
        return await _out(s, r)


@tenant_router.get("/lifecycle/requests/{request_id}/download")
async def download(request_id: uuid.UUID, request: Request, ctx: Ctx) -> Response:
    await check_permission(request, "governance.tenant.export", Resource(type="tenant"))
    async with _db(request).session(ctx) as s:
        r = await s.get(LifecycleRequest, request_id)
    if r is None or r.kind != "export" or not r.result_key:
        raise NotFound("No archive for this request")
    data = await request.app.state.blobs.get(r.result_key)
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "content-disposition": f'attachment; filename="nexiqon-export-{request_id}.zip"',
            "cache-control": "private, no-store",
        },
    )


# ===================================================================== retention (G-01)


class RetentionOut(BaseModel):
    id: uuid.UUID
    started_by: str
    status: str
    policy: dict[str, object]
    purged: dict[str, dict[str, int]]
    errors: dict[str, str]
    created_at: datetime
    finished_at: datetime | None


@tenant_router.get("/retention/runs", response_model=list[RetentionOut])
async def retention_runs(request: Request, ctx: Ctx) -> list[RetentionOut]:
    await check_permission(request, "governance.retention.read", Resource(type="tenant"))
    async with _db(request).session(ctx) as s:
        rows = await s.scalars(
            select(RetentionRun).order_by(RetentionRun.created_at.desc()).limit(30)
        )
        return [RetentionOut.model_validate(r, from_attributes=True) for r in rows]


@tenant_router.post("/retention/runs", response_model=RetentionOut, status_code=202)
async def run_retention(request: Request, ctx: Ctx) -> RetentionOut:
    """Purge what this organization's retention profile says has expired, now (it also runs
    every night)."""
    await check_permission(request, "governance.retention.run", Resource(type="tenant"))
    temporal = _temporal(request)
    await remember_tenant(_db(request), ctx.tenant_id)
    async with _db(request).session(ctx) as s:
        run = RetentionRun(
            tenant_id=ctx.tenant_id,
            started_by=ctx.actor_id,
            status="running",
            policy={},
            purged={},
            errors={},
        )
        s.add(run)
        await s.flush()
        out = RetentionOut.model_validate(run, from_attributes=True)
    scope = TenantScope.of(ctx)
    await temporal.start_workflow(  # type: ignore[attr-defined]
        "governance.RetentionSweep",
        args=[scope, str(out.id)],
        id=workflow_id(scope, "retention", str(out.id)),
        task_queue=request.app.state.settings.task_queue,
    )
    return out
