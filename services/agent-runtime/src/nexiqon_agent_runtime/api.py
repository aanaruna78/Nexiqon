"""HTTP API for agent-runtime. Contract: contracts/openapi/agent-runtime.json."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexiqon_agent_runtime.engine import STAFF_ROLES, Engine
from nexiqon_agent_runtime.models import Run
from nexiqon_agent_runtime.spec import GraphError, validate_graph
from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.errors import NexiqonError, NotFound, ServiceUnavailable
from nexiqon_core.tenancy import TenantContext, require_current_context

public_router = APIRouter(tags=["agent-runtime"])
tenant_router = APIRouter(prefix="/v1", tags=["agent-runtime"])

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


def _engine(request: Request) -> Engine:
    engine: Engine | None = request.app.state.engine
    if engine is None:
        raise ServiceUnavailable("Agent runtime storage is not configured")
    return engine


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class RunIn(BaseModel):
    thread_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,100}$")
    input: str | None = Field(default=None, max_length=8000)
    resume: Any = None  # answer to a clarifying question, or {"approved": bool}
    history: list[Message] = Field(default_factory=list, max_length=50)
    locale: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    handoff: bool = False  # the user asked for a person (widget button): skip intent routing


class RunOut(BaseModel):
    run_id: uuid.UUID
    status: str
    answer: dict[str, Any] | None
    interrupt: dict[str, Any] | None
    handoff: dict[str, Any] | None
    intent: str | None
    route: str | None
    steps: list[dict[str, Any]]
    error: str | None
    retention_profile: str | None


@tenant_router.post("/agents/{agent}/runs", response_model=RunOut)
async def run_agent(
    agent: Annotated[str, Field(pattern=NAME)], body: RunIn, request: Request, ctx: Ctx
) -> RunOut:
    """Run one turn of an agent on a thread, or resume it after a clarifying question/approval."""
    await check_permission(request, "agent.query.run", Resource(type="agent", id=agent))
    token = str(request.state.context_token)
    result = await _engine(request).run(
        ctx,
        token,
        agent,
        body.thread_id,
        text=body.input,
        resume=body.resume,
        history=[m.model_dump() for m in body.history],
        locale=body.locale.split("-")[0],
        handoff=body.handoff,
    )
    return RunOut(**result.__dict__)


def sse(kind: str, data: Any) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n".encode()


@tenant_router.post(
    "/agents/{agent}/runs/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_agent(
    agent: Annotated[str, Field(pattern=NAME)], body: RunIn, request: Request, ctx: Ctx
) -> StreamingResponse:
    """The same turn as ``/runs`` as server-sent events (CH-01): ``run``, ``status``, ``sources``,
    ``tool``, ``delta`` (answer text as it is written), then ``result`` (the RunOut, with the
    checked answer and citations, which replaces the streamed text)."""
    await check_permission(request, "agent.query.run", Resource(type="agent", id=agent))
    events = _engine(request).stream(
        ctx,
        str(request.state.context_token),
        agent,
        body.thread_id,
        text=body.input,
        resume=body.resume,
        history=[m.model_dump() for m in body.history],
        locale=body.locale.split("-")[0],
        handoff=body.handoff,
    )
    first = await anext(events)  # refusals surface as ordinary HTTP errors

    async def body_() -> AsyncIterator[bytes]:
        event: dict[str, Any] | None = first
        try:
            while event is not None:
                kind = str(event["type"])
                if kind == "result":
                    yield sse(kind, RunOut(**event["result"].__dict__).model_dump(mode="json"))
                    return
                yield sse(kind, {k: v for k, v in event.items() if k != "type"})
                event = await anext(events, None)
        except NexiqonError as exc:
            yield sse("error", {"code": exc.code, "detail": exc.detail})

    return StreamingResponse(
        body_(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


class RunTrace(BaseModel):
    id: uuid.UUID
    thread_id: str
    agent: str
    agent_versions: dict[str, Any]
    kind: str
    status: str
    steps: list[dict[str, Any]]
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


@tenant_router.get("/runs/{run_id}", response_model=RunTrace)
async def get_run(run_id: uuid.UUID, request: Request, ctx: Ctx) -> RunTrace:
    """A run's step-by-step trace (Answer Inspector). Callers see their own runs; staff see all."""
    await check_permission(request, "agent.runs.read", Resource(type="run", id=str(run_id)))
    async with _engine(request).db.session(ctx) as s:
        run = await s.get(Run, run_id)
    if run is None or (run.actor_id != ctx.actor_id and not ctx.has_role(*STAFF_ROLES, "editor")):
        raise NotFound("Run not found")
    return RunTrace.model_validate(run, from_attributes=True)


@tenant_router.get("/threads/{thread_id}/runs", response_model=list[RunTrace])
async def thread_runs(thread_id: str, request: Request, ctx: Ctx) -> list[RunTrace]:
    await check_permission(request, "agent.runs.read", Resource(type="run"))
    async with _engine(request).db.session(ctx) as s:
        rows = (
            await s.scalars(select(Run).where(Run.thread_id == thread_id).order_by(Run.created_at))
        ).all()
    staff = ctx.has_role(*STAFF_ROLES, "editor")
    return [
        RunTrace.model_validate(r, from_attributes=True)
        for r in rows
        if staff or r.actor_id == ctx.actor_id
    ]


class GraphCheck(BaseModel):
    valid: bool
    problems: list[str]


@tenant_router.post("/graphs/validate", response_model=GraphCheck)
async def validate(graph: dict[str, Any], request: Request, ctx: Ctx) -> GraphCheck:
    """Check a declarative graph before publishing it (Domain Pack editor, agent overrides)."""
    await check_permission(request, "agent.graphs.read", Resource(type="graph"))
    try:
        validate_graph(graph)
    except GraphError as exc:
        return GraphCheck(valid=False, problems=exc.problems)
    return GraphCheck(valid=True, problems=[])
