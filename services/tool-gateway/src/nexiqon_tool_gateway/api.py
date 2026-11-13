"""HTTP API for tool-gateway (T-01). Contract: contracts/openapi/tool-gateway.json.

Every invocation, in order: tool deployed -> on the agent's allowlist -> caller authorised for the
risk level -> arguments valid -> confirmation (writes) -> idempotency -> rate limit and circuit ->
request built from the definition (caller placeholders, host allowlist) -> credential applied ->
result minimised and scrubbed -> call logged and an audit event emitted (never arguments' secrets,
never credential values).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import jsonschema
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import (
    BadRequest,
    Conflict,
    Forbidden,
    NexiqonError,
    NotFound,
    ServiceUnavailable,
)
from nexiqon_core.events import add_event
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_tool_gateway.executor import ToolFailure, execute, prepare
from nexiqon_tool_gateway.models import Approval, Outbox, ToolCall
from nexiqon_tool_gateway.openapi import OpenApiError, import_spec
from nexiqon_tool_gateway.registry import RISK_ORDER, ToolDef
from nexiqon_tool_gateway.secrets import SecretNotFound, SecretsUnavailable, check_name

public_router = APIRouter(tags=["tool-gateway"])
tenant_router = APIRouter(prefix="/v1", tags=["tool-gateway"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
NAME = r"^[a-z0-9][a-z0-9-]{1,62}$"
SERVICE = "tool-gateway"


class TooMany(NexiqonError):
    status, code, title = 429, "rate_limited", "Too many calls to this tool"


class InvalidArguments(NexiqonError):
    status, code, title = 422, "invalid_arguments", "The arguments do not match the tool"


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
        raise ServiceUnavailable("Tool gateway storage is not configured")
    return db


def args_hash(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _checked(
    request: Request, ctx: TenantContext, name: str, agent: str, arguments: dict[str, Any]
) -> tuple[ToolDef, str]:
    """Steps shared by invoke and approval requests. Returns the tool and its effective risk."""
    registry = request.app.state.registry
    tool: ToolDef = await registry.tool(ctx.tenant_id, name)
    allowed, pack_risks = await registry.agent_tools(ctx.tenant_id, agent)
    if name not in allowed:
        raise Forbidden(f"Assistant {agent!r} may not use tool {name!r}")
    risk = max(tool.risk, pack_risks.get(name, "read"), key=RISK_ORDER.index)
    await check_permission(request, f"tool.invoke.{risk}", Resource(type="tool", id=name))
    if len(json.dumps(arguments).encode()) > request.app.state.settings.max_argument_bytes:
        raise InvalidArguments("Arguments are too large")
    schema = tool.spec.get("input_schema") or {"type": "object"}
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(arguments),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        problem = InvalidArguments("; ".join(e.message for e in errors[:5]))
        problem.errors = [
            {"path": "/".join(map(str, e.absolute_path)) or "(root)", "message": e.message}
            for e in errors[:20]
        ]
        raise problem
    return tool, risk


# ===================================================================== definitions


@tenant_router.get("/tools/{name}")
async def describe(name: str, request: Request, ctx: Ctx) -> dict[str, Any]:
    """What a caller (and a model choosing arguments) may know: description, input schema, risk."""
    await check_permission(request, "tool.definitions.read", Resource(type="tool", id=name))
    tool: ToolDef = await request.app.state.registry.tool(ctx.tenant_id, name)
    return tool.public()


# ===================================================================== invocation


class InvokeIn(BaseModel):
    agent: str = Field(pattern=NAME)
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,200}$")
    approval_id: uuid.UUID | None = None
    conversation_id: str | None = Field(default=None, max_length=100)


class InvokeOut(BaseModel):
    call_id: uuid.UUID | None
    ok: bool
    result: Any = None
    error: str | None = None
    detail: str | None = None
    http_status: int | None = None
    truncated: bool = False
    replayed: bool = False
    classification: str


async def _use_approval(
    request: Request, ctx: TenantContext, tool: ToolDef, approval_id: uuid.UUID | None, digest: str
) -> uuid.UUID:
    if approval_id is None:
        raise Forbidden(f"Tool {tool.name!r} needs the user's confirmation first")
    async with _db(request).session(ctx) as s:
        approval = await s.get(Approval, approval_id, with_for_update=True)
        now = datetime.now(UTC)
        if (
            approval is None
            or approval.kind != "confirmation"
            or approval.tool != tool.name
            or approval.actor_id != ctx.actor_id
        ):
            raise Forbidden("This confirmation does not belong to this call")
        if approval.args_hash != digest:
            raise Forbidden("The arguments differ from what was confirmed")
        if approval.status != "approved":
            raise Conflict(f"Confirmation is {approval.status}")
        if approval.expires_at <= now:
            approval.status = "expired"
            raise Conflict("Confirmation expired")
        approval.status = "used"  # one confirmation, one call
    return approval_id


@tenant_router.post("/tools/{name}/invoke", response_model=InvokeOut)
async def invoke(
    name: Annotated[str, Field(pattern=NAME)], body: InvokeIn, request: Request, ctx: Ctx
) -> InvokeOut:
    settings = request.app.state.settings
    tool, risk = await _checked(request, ctx, name, body.agent, body.arguments)
    digest = args_hash(body.arguments)
    if risk != "read" and not body.idempotency_key:
        raise BadRequest("Write tools need an idempotency_key")
    db = _db(request)
    if body.idempotency_key:
        async with db.session(ctx) as s:
            prior = await s.scalar(
                select(ToolCall).where(
                    ToolCall.tool == name, ToolCall.idempotency_key == body.idempotency_key
                )
            )
        if prior is not None:
            if prior.args_hash != digest:
                raise Conflict("This idempotency key was used with different arguments")
            if prior.status == "running":
                raise Conflict("This call is still running")
            stored = prior.result or {}
            return InvokeOut(
                call_id=prior.id,
                ok=prior.status == "ok",
                result=stored.get("value"),
                error=prior.error_code,
                http_status=prior.http_status,
                truncated=bool(stored.get("truncated")),
                replayed=True,
                classification=tool.result_classification,
            )
    approval_id = (
        await _use_approval(request, ctx, tool, body.approval_id, digest)
        if tool.needs_confirmation
        else None
    )
    guards = request.app.state.guards
    if not guards.allow(ctx.tenant_id, name, tool.spec.get("rate_limit_per_minute")):
        raise TooMany(
            f"Tool {name!r} allows {tool.spec.get('rate_limit_per_minute')} calls per minute"
        )
    try:
        async with db.session(ctx) as s:
            call = ToolCall(
                tenant_id=ctx.tenant_id,
                tool=name,
                tool_version=tool.version,
                agent=body.agent,
                actor_id=ctx.actor_id,
                conversation_id=body.conversation_id,
                risk=risk,
                status="running",
                idempotency_key=body.idempotency_key,
                args_hash=digest,
                arguments=body.arguments,
                approval_id=approval_id,
            )
            s.add(call)
            await s.flush()
            call_id = call.id
    except IntegrityError as exc:
        raise Conflict("This idempotency key is already in use") from exc

    started = time.perf_counter()
    out = InvokeOut(call_id=call_id, ok=False, classification=tool.result_classification)
    secret: str | None = None
    try:
        if guards.circuit_open(ctx.tenant_id, name):
            raise ToolFailure("circuit_open", "The tool is failing; calls are paused for a moment")
        if tool.spec.get("kind") == "approval":
            async with db.session(ctx) as s:
                task = Approval(
                    tenant_id=ctx.tenant_id,
                    tool=name,
                    agent=body.agent,
                    kind="human",
                    actor_id=ctx.actor_id,
                    conversation_id=body.conversation_id,
                    arguments=body.arguments,
                    args_hash=digest,
                    summary=f"{tool.spec.get('description', name)}"[:1000],
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
                s.add(task)
                await s.flush()
                out.ok, out.result = True, {"status": "requested", "request_id": str(task.id)}
        else:
            prepared = prepare(
                tool,
                body.arguments,
                actor_id=ctx.actor_id,
                tenant=ctx.tenant_id,
                allow_http=settings.allow_insecure_http,
            )
            if tool.spec.get("credential_ref"):
                try:
                    secret = await request.app.state.secrets.get(
                        ctx.tenant_id, str(tool.spec["credential_ref"]).removeprefix("secret://")
                    )
                except SecretNotFound as exc:
                    raise ToolFailure(
                        "credentials_missing", "The credential this tool needs is not set up"
                    ) from exc
                except SecretsUnavailable as exc:
                    raise ToolFailure(
                        "secrets_unavailable", "The secrets store is unavailable", retryable=True
                    ) from exc
            result, status, truncated = await execute(
                request.app.state.fetcher,
                tool,
                prepared,
                secret=secret,
                timeout_ms=int(tool.spec.get("timeout_ms") or settings.default_timeout_ms),
                max_result_bytes=int(
                    tool.spec.get("max_result_bytes") or settings.default_max_result_bytes
                ),
            )
            out.ok, out.result, out.http_status, out.truncated = True, result, status, truncated
        guards.record(ctx.tenant_id, name, failed=False)
    except ToolFailure as exc:
        out.error, out.detail, out.http_status = exc.code, exc.detail, exc.http_status
        if exc.retryable:
            guards.record(ctx.tenant_id, name, failed=True)
    latency = int((time.perf_counter() - started) * 1000)
    async with db.session(ctx) as s:
        row = await s.get(ToolCall, call_id)
        assert row is not None
        row.status = "ok" if out.ok else "error"
        row.error_code, row.http_status, row.latency_ms = out.error, out.http_status, latency
        row.result = {"value": out.result, "truncated": out.truncated} if out.ok else None
        add_event(
            s,
            Outbox,
            ctx,
            source=SERVICE,
            type="nexiqon.tool-gateway.call.completed",
            subject=name,
            data={
                "call_id": str(call_id),
                "tool": name,
                "agent": body.agent,
                "risk": risk,
                "ok": out.ok,
                "error": out.error,
                "http_status": out.http_status,
                "latency_ms": latency,
                "approval_id": str(approval_id) if approval_id else None,
            },
        )
    return out


# ===================================================================== confirmations and approvals


class ApprovalIn(BaseModel):
    agent: str = Field(pattern=NAME)
    arguments: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = Field(default=None, max_length=100)


class ApprovalOut(BaseModel):
    id: uuid.UUID
    tool: str
    agent: str
    kind: str
    actor_id: str
    arguments: dict[str, Any]
    summary: str
    status: str
    decided_by: str | None
    decided_at: datetime | None
    expires_at: datetime
    created_at: datetime


def _summary(tool: ToolDef, arguments: dict[str, Any]) -> str:
    shown = ", ".join(f"{k}: {v}" for k, v in list(arguments.items())[:8])
    return f"{tool.spec.get('description', tool.name)}" + (f" ({shown})" if shown else "")


@tenant_router.post("/tools/{name}/approvals", response_model=ApprovalOut, status_code=201)
async def request_confirmation(
    name: Annotated[str, Field(pattern=NAME)], body: ApprovalIn, request: Request, ctx: Ctx
) -> ApprovalOut:
    """Record exactly what will run, for the caller to confirm (writes always need this)."""
    tool, _ = await _checked(request, ctx, name, body.agent, body.arguments)
    ttl = int(request.app.state.settings.approval_ttl_seconds)
    async with _db(request).session(ctx) as s:
        approval = Approval(
            tenant_id=ctx.tenant_id,
            tool=name,
            agent=body.agent,
            kind="confirmation",
            actor_id=ctx.actor_id,
            conversation_id=body.conversation_id,
            arguments=body.arguments,
            args_hash=args_hash(body.arguments),
            summary=_summary(tool, body.arguments)[:1000],
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
        )
        s.add(approval)
        await s.flush()
        await s.refresh(approval)
        return ApprovalOut.model_validate(approval, from_attributes=True)


class DecisionIn(BaseModel):
    approved: bool


@tenant_router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
async def decide(
    approval_id: uuid.UUID, body: DecisionIn, request: Request, ctx: Ctx
) -> ApprovalOut:
    """Confirmations are decided by the person who asked; human approvals by authorised staff."""
    async with _db(request).session(ctx) as s:
        approval = await s.get(Approval, approval_id, with_for_update=True)
        if approval is None:
            raise NotFound("Approval not found")
        if approval.kind == "confirmation":
            if approval.actor_id != ctx.actor_id:
                raise NotFound("Approval not found")
        else:
            await check_permission(
                request, "tool.approvals.decide", Resource(type="approval", id=str(approval_id))
            )
        if approval.status != "pending":
            raise Conflict(f"Approval is already {approval.status}")
        if approval.expires_at <= datetime.now(UTC):
            approval.status = "expired"
            raise Conflict("Approval expired")
        approval.status = "approved" if body.approved else "declined"
        approval.decided_by, approval.decided_at = ctx.actor_id, datetime.now(UTC)
        add_event(
            s,
            Outbox,
            ctx,
            source=SERVICE,
            type="nexiqon.tool-gateway.approval.decided",
            subject=str(approval_id),
            data={
                "approval_id": str(approval_id),
                "tool": approval.tool,
                "kind": approval.kind,
                "status": approval.status,
            },
        )
        await s.flush()
        await s.refresh(approval)
        return ApprovalOut.model_validate(approval, from_attributes=True)


@tenant_router.get("/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    request: Request,
    ctx: Ctx,
    status: str | None = None,
    kind: Literal["confirmation", "human"] | None = None,
    limit: int = 50,
) -> list[ApprovalOut]:
    """The approvals log (Studio Actions)."""
    await check_permission(request, "tool.approvals.read", Resource(type="approval"))
    query = select(Approval).order_by(Approval.created_at.desc()).limit(min(max(limit, 1), 200))
    if status:
        query = query.where(Approval.status == status)
    if kind:
        query = query.where(Approval.kind == kind)
    async with _db(request).session(ctx) as s:
        return [
            ApprovalOut.model_validate(a, from_attributes=True)
            for a in (await s.scalars(query)).all()
        ]


class CallOut(BaseModel):
    id: uuid.UUID
    tool: str
    tool_version: int
    agent: str
    actor_id: str
    risk: str
    status: str
    error_code: str | None
    http_status: int | None
    latency_ms: int
    approval_id: uuid.UUID | None
    created_at: datetime


@tenant_router.get("/calls", response_model=list[CallOut])
async def list_calls(
    request: Request, ctx: Ctx, tool: str | None = None, limit: int = 50
) -> list[CallOut]:
    """The call log (no arguments or results: open a call's conversation for context)."""
    await check_permission(request, "tool.calls.read", Resource(type="call"))
    query = select(ToolCall).order_by(ToolCall.created_at.desc()).limit(min(max(limit, 1), 200))
    if tool:
        query = query.where(ToolCall.tool == tool)
    async with _db(request).session(ctx) as s:
        return [
            CallOut.model_validate(c, from_attributes=True) for c in (await s.scalars(query)).all()
        ]


# ===================================================================== dry run (Actions console)


class DryRunIn(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@tenant_router.post("/tools/{name}/dry-run")
async def dry_run(
    name: Annotated[str, Field(pattern=NAME)], body: DryRunIn, request: Request, ctx: Ctx
) -> dict[str, Any]:
    """Validate arguments and show the request that would be sent. Nothing is sent; no secret is read."""
    await check_permission(request, "tool.definitions.test", Resource(type="tool", id=name))
    tool: ToolDef = await request.app.state.registry.tool(ctx.tenant_id, name)
    problems = [
        e.message
        for e in jsonschema.Draft202012Validator(
            tool.spec.get("input_schema") or {"type": "object"}
        ).iter_errors(body.arguments)
    ]
    if problems or tool.spec.get("kind") != "rest":
        return {"valid": not problems, "problems": problems, "request": None}
    try:
        p = prepare(
            tool,
            body.arguments,
            actor_id=ctx.actor_id,
            tenant=ctx.tenant_id,
            allow_http=request.app.state.settings.allow_insecure_http,
        )
    except ToolFailure as exc:
        return {"valid": False, "problems": [exc.detail], "request": None}
    auth = (tool.spec.get("request") or {}).get("auth")
    return {
        "valid": True,
        "problems": [],
        "request": {
            "method": p.method,
            "url": p.url,
            "query": p.query,
            "body": p.body,
            "headers": sorted(p.headers),
            "credential": tool.spec.get("credential_ref"),
            "auth": auth.get("scheme") if auth else None,
        },
    }


# ===================================================================== credentials (write-only)


class CredentialIn(BaseModel):
    value: str = Field(min_length=1, max_length=8192)


@tenant_router.put("/credentials/{name}", status_code=204)
async def put_credential(name: str, body: CredentialIn, request: Request, ctx: Ctx) -> Response:
    """Store a credential for this workspace. It can be replaced or deleted, never read back."""
    await check_permission(request, "tool.credentials.write", Resource(type="credential", id=name))
    try:
        await request.app.state.secrets.put(ctx.tenant_id, check_name(name), body.value)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    except SecretsUnavailable as exc:
        raise ServiceUnavailable("The secrets store is unavailable") from exc
    async with _db(request).session(ctx) as s:
        add_event(
            s,
            Outbox,
            ctx,
            source=SERVICE,
            type="nexiqon.tool-gateway.credential.changed",
            subject=name,
            data={"name": name, "action": "set"},
        )
    return Response(status_code=204)


@tenant_router.get("/credentials")
async def list_credentials(request: Request, ctx: Ctx) -> list[dict[str, Any]]:
    await check_permission(request, "tool.credentials.read", Resource(type="credential"))
    try:
        names = await request.app.state.secrets.names(ctx.tenant_id)
    except SecretsUnavailable as exc:
        raise ServiceUnavailable("The secrets store is unavailable") from exc
    return [{"name": n, "updated_at": at} for n, at in sorted(names.items())]


@tenant_router.delete("/credentials/{name}", status_code=204)
async def delete_credential(name: str, request: Request, ctx: Ctx) -> Response:
    await check_permission(request, "tool.credentials.write", Resource(type="credential", id=name))
    try:
        await request.app.state.secrets.delete(ctx.tenant_id, check_name(name))
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    async with _db(request).session(ctx) as s:
        add_event(
            s,
            Outbox,
            ctx,
            source=SERVICE,
            type="nexiqon.tool-gateway.credential.changed",
            subject=name,
            data={"name": name, "action": "delete"},
        )
    return Response(status_code=204)


# ===================================================================== OpenAPI import


class OpenApiIn(BaseModel):
    spec: str = Field(min_length=10, max_length=2_000_000)
    base_url: str | None = Field(default=None, pattern=r"^https?://")
    operations: list[str] | None = None
    credential_ref: str | None = Field(default=None, pattern=NAME)
    auth_scheme: Literal["bearer", "header", "basic"] = "bearer"


@tenant_router.post("/openapi/import")
async def openapi_import(body: OpenApiIn, request: Request, ctx: Ctx) -> list[dict[str, Any]]:
    """Turn an OpenAPI 3 document into tool definitions (saved and published through config)."""
    await check_permission(request, "tool.openapi.import", Resource(type="tool"))
    try:
        return import_spec(
            body.spec,
            base_url=body.base_url,
            operations=body.operations,
            credential_ref=body.credential_ref,
            auth_scheme=body.auth_scheme,
        )
    except OpenApiError as exc:
        raise BadRequest(str(exc)) from exc
