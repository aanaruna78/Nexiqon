"""HTTP API for model-gateway. Contract: contracts/openapi/model-gateway.json."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.errors import BadRequest, NexiqonError, ServiceUnavailable, Unauthorized
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_model_gateway.gateway import Caller, ChatRequest, Gateway, Result
from nexiqon_model_gateway.models import UsageRecord
from nexiqon_model_gateway.settings import Classification
from nexiqon_model_gateway.types import Message, ToolCall, ToolSpec, Usage

public_router = APIRouter(tags=["model-gateway"])
tenant_router = APIRouter(prefix="/v1", tags=["model-gateway"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
PROFILE = r"^[a-z0-9][a-z0-9-]{1,62}$"


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


def _gateway(request: Request) -> Gateway:
    gateway: Gateway = request.app.state.gateway
    return gateway


async def _caller(
    request: Request,
    ctx: TenantContext,
    profile: str | None,
    classification: Classification,
    conversation_id: str | None = None,
) -> Caller:
    await check_permission(
        request, "model.inference.run", Resource(type="model_profile", id=profile)
    )
    token = getattr(request.state, "context_token", None)
    if token is None:
        raise Unauthorized("Missing tenant context")
    return Caller(ctx, token, classification, conversation_id)


class Route(BaseModel):
    """Which profile served the call and why (shown in Playground and traces)."""

    requested_profile: str
    profile: str
    routed: bool
    fallback_used: bool
    provider: str
    model: str
    redacted: bool


class Cost(BaseModel):
    usage: Usage
    cost_usd: str


def _route(result: Result[Any]) -> Route:
    t = result.target
    return Route(
        requested_profile=t.requested,
        profile=t.name,
        routed=t.name != t.requested and not t.fallback,
        fallback_used=t.fallback,
        provider=result.provider,
        model=result.model,
        redacted=result.redacted,
    )


# ===================================================================== chat


class ChatIn(BaseModel):
    profile: str | None = Field(default=None, pattern=PROFILE)
    messages: list[Message] = Field(min_length=1, max_length=500)
    tools: list[ToolSpec] = Field(default_factory=list, max_length=128)
    response_schema: dict[str, Any] | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=64000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    classification: Classification = "internal"
    conversation_id: str | None = Field(default=None, max_length=200)


class ChatOut(BaseModel):
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str
    route: Route
    usage: Usage
    cost_usd: str


@tenant_router.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, request: Request, ctx: Ctx) -> ChatOut:
    """Chat completion through the tenant's model profile (routing, floors, budgets, redaction)."""
    caller = await _caller(request, ctx, body.profile, body.classification, body.conversation_id)
    result = await _gateway(request).chat(
        caller,
        ChatRequest(
            messages=body.messages,
            tools=body.tools,
            response_schema=body.response_schema,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
        ),
        body.profile,
    )
    out = result.output
    return ChatOut(
        content=out.content,
        tool_calls=out.tool_calls,
        finish_reason=out.finish_reason,
        route=_route(result),
        usage=result.usage,
        cost_usd=str(result.cost_usd),
    )


@tenant_router.post("/chat/stream")
async def chat_stream(body: ChatIn, request: Request, ctx: Ctx) -> StreamingResponse:
    """Streamed chat as server-sent events: ``delta`` chunks, then ``done`` (route, usage, cost)
    or ``error``. Every check of /v1/chat applies before the first byte."""
    caller = await _caller(request, ctx, body.profile, body.classification, body.conversation_id)
    gateway = _gateway(request)
    stream = gateway.chat_stream(
        caller,
        ChatRequest(
            messages=body.messages,
            tools=body.tools,
            response_schema=body.response_schema,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
        ),
        body.profile,
    )
    first = await anext(stream)  # routing, floors and budgets fail here, as a normal HTTP error

    async def events() -> AsyncIterator[bytes]:
        event: dict[str, Any] | None = first
        try:
            while event is not None:
                kind = "done" if event.get("done") else "delta"
                payload = {k: v for k, v in event.items() if k != "done"}
                yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n".encode()
                event = await anext(stream, None)
        except NexiqonError as exc:
            yield f"event: error\ndata: {json.dumps({'code': exc.code, 'detail': exc.detail})}\n\n".encode()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


# ===================================================================== embeddings


class EmbedIn(BaseModel):
    profile: str | None = Field(default=None, pattern=PROFILE)
    inputs: list[Annotated[str, Field(max_length=32000)]] = Field(min_length=1)
    input_type: Literal["document", "query"] = "document"
    classification: Classification = "internal"


class EmbedOut(BaseModel):
    vectors: list[list[float]]
    dimensions: int
    route: Route
    usage: Usage
    cost_usd: str


@tenant_router.post("/embeddings", response_model=EmbedOut)
async def embeddings(body: EmbedIn, request: Request, ctx: Ctx) -> EmbedOut:
    """Embeddings (1024 dimensions). Never routed or failed over, to keep one vector space."""
    gateway = _gateway(request)
    if len(body.inputs) > gateway.settings.max_batch_inputs:
        raise BadRequest(f"At most {gateway.settings.max_batch_inputs} inputs per request")
    caller = await _caller(request, ctx, body.profile, body.classification)
    result = await gateway.embed(caller, body.inputs, body.input_type, body.profile)
    return EmbedOut(
        vectors=result.output,
        dimensions=len(result.output[0]),
        route=_route(result),
        usage=result.usage,
        cost_usd=str(result.cost_usd),
    )


# ===================================================================== reranking


class RerankIn(BaseModel):
    profile: str | None = Field(default=None, pattern=PROFILE)
    query: str = Field(min_length=1, max_length=8000)
    documents: list[Annotated[str, Field(max_length=32000)]] = Field(min_length=1)
    top_n: int = Field(default=8, ge=1, le=200)
    classification: Classification = "internal"


class Ranked(BaseModel):
    index: int
    score: float


class RerankOut(BaseModel):
    results: list[Ranked]
    route: Route


@tenant_router.post("/rerank", response_model=RerankOut)
async def rerank(body: RerankIn, request: Request, ctx: Ctx) -> RerankOut:
    """Rerank candidate passages for a query (best first)."""
    gateway = _gateway(request)
    if len(body.documents) > gateway.settings.max_rerank_documents:
        raise BadRequest(f"At most {gateway.settings.max_rerank_documents} documents per request")
    caller = await _caller(request, ctx, body.profile, body.classification)
    result = await gateway.rerank(caller, body.query, body.documents, body.top_n, body.profile)
    return RerankOut(
        results=[Ranked(index=i, score=s) for i, s in result.output], route=_route(result)
    )


# ===================================================================== usage


class UsageRow(BaseModel):
    profile: str
    provider: str
    model: str
    operation: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str


class UsageReport(BaseModel):
    month: str
    rows: list[UsageRow]
    total_cost_usd: str


@tenant_router.get("/usage", response_model=UsageReport)
async def usage(
    request: Request,
    ctx: Ctx,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> UsageReport:
    """Token usage and estimated cost for a calendar month (UTC), by profile and model."""
    await check_permission(request, "model.usage.read", Resource(type="usage"))
    db = _gateway(request).db
    if db is None:
        raise ServiceUnavailable("Usage storage is not configured")
    now = datetime.now(UTC)
    year, mon = (int(p) for p in month.split("-")) if month else (now.year, now.month)
    start = datetime(year, mon, 1, tzinfo=UTC)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=UTC)
    u = UsageRecord
    async with db.session(ctx) as s:
        result = await s.execute(
            select(
                u.profile,
                u.provider,
                u.model,
                u.operation,
                func.count(),
                func.sum(u.input_tokens),
                func.sum(u.output_tokens),
                func.sum(u.cost_usd),
            )
            .where(u.created_at >= start, u.created_at < end)
            .group_by(u.profile, u.provider, u.model, u.operation)
            .order_by(u.profile, u.model, u.operation)
        )
        rows = [
            UsageRow(
                profile=r[0],
                provider=r[1],
                model=r[2],
                operation=r[3],
                calls=int(r[4]),
                input_tokens=int(r[5] or 0),
                output_tokens=int(r[6] or 0),
                cost_usd=str(Decimal(r[7] or 0)),
            )
            for r in result.all()
        ]
    total = sum((Decimal(r.cost_usd) for r in rows), Decimal(0))
    return UsageReport(month=f"{year:04d}-{mon:02d}", rows=rows, total_cost_usd=str(total))
