"""HTTP API for conversation. Contract: contracts/openapi/conversation.json.

A turn: store the user's message, run the agent (agent-runtime, with the caller's own token so
every permission and access rule applies to them), store the reply with its answer contract.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexiqon_conversation.models import Conversation, Feedback, Message, Outbox
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
from nexiqon_core.profiles import ProfileResolver
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext, require_current_context

public_router = APIRouter(tags=["conversation"])
tenant_router = APIRouter(prefix="/v1", tags=["conversation"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
NAME = r"^[a-z0-9][a-z0-9-]{1,62}$"
SERVICE = "conversation"
FALLBACK = {
    "en": "Sorry, something went wrong on our side. Please try again in a moment.",
    "ar": "عذرًا، حدث خطأ من جانبنا. يرجى المحاولة بعد قليل.",
    "es": "Lo sentimos, algo falló por nuestra parte. Inténtalo de nuevo en un momento.",
}
ASK_FOR_PERSON = {
    "en": "I'd like to talk to a person.",
    "ar": "أود التحدث إلى شخص.",
    "es": "Me gustaría hablar con una persona.",
}


class AgentFailed(NexiqonError):
    status, code, title = 502, "agent_failed", "The assistant could not answer"


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
        raise ServiceUnavailable("Conversation storage is not configured")
    return db


async def _sees_all(request: Request) -> bool:
    """Staff (members and up) read every conversation; end users and widgets only their own."""
    try:
        await check_permission(request, "conversation.all.read", Resource(type="conversation"))
    except Forbidden:
        return False
    return True


async def _load(
    request: Request, ctx: TenantContext, conversation_id: uuid.UUID, *, write: bool = False
) -> Conversation:
    async with _db(request).session(ctx) as s:
        c = await s.get(Conversation, conversation_id)
    if c is None:
        raise NotFound("Conversation not found")
    own = c.actor_id == ctx.actor_id
    if (write and not own) or (not write and not own and not await _sees_all(request)):
        raise NotFound("Conversation not found")  # never confirm that someone else's exists
    return c


# ===================================================================== shapes


class ConversationIn(BaseModel):
    agent: str = Field(pattern=NAME)
    channel: Literal["api", "widget", "studio"] = "api"
    locale: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")


class ConversationOut(BaseModel):
    id: uuid.UUID
    agent: str
    channel: str
    locale: str
    actor_id: str
    status: str
    title: str | None
    handoff_summary: str | None
    created_at: datetime
    last_message_at: datetime | None
    retain_until: datetime | None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    contract: dict[str, Any]
    run_id: uuid.UUID | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class TurnOut(BaseModel):
    conversation: ConversationOut
    user_message: MessageOut | None
    reply: MessageOut | None


def _c(c: Conversation) -> ConversationOut:
    return ConversationOut.model_validate(c, from_attributes=True)


def _m(m: Message) -> MessageOut:
    return MessageOut.model_validate(m, from_attributes=True)


# ===================================================================== conversations


@tenant_router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(body: ConversationIn, request: Request, ctx: Ctx) -> ConversationOut:
    await check_permission(request, "conversation.messages.create", Resource(type="conversation"))
    async with _db(request).session(ctx) as s:
        c = Conversation(
            tenant_id=ctx.tenant_id,
            agent=body.agent,
            channel=body.channel,
            locale=body.locale.split("-")[0],
            actor_id=ctx.actor_id,
            actor_type=ctx.actor_type,
            status="active",
            # Until the first turn tells us the agent's retention profile, the default applies.
            retain_until=datetime.now(UTC)
            + timedelta(days=int(request.app.state.settings.default_retention_days)),
        )
        s.add(c)
        await s.flush()
        await s.refresh(c)
        return _c(c)


@tenant_router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    request: Request, ctx: Ctx, mine: bool = False, limit: int = 50
) -> list[ConversationOut]:
    await check_permission(request, "conversation.own.read", Resource(type="conversation"))
    query = (
        select(Conversation).order_by(Conversation.created_at.desc()).limit(min(max(limit, 1), 200))
    )
    if mine or not await _sees_all(request):
        query = query.where(Conversation.actor_id == ctx.actor_id)
    async with _db(request).session(ctx) as s:
        return [_c(c) for c in (await s.scalars(query)).all()]


@tenant_router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, request: Request, ctx: Ctx
) -> ConversationDetail:
    await check_permission(
        request, "conversation.own.read", Resource(type="conversation", id=str(conversation_id))
    )
    c = await _load(request, ctx, conversation_id)
    async with _db(request).session(ctx) as s:
        messages = (
            await s.scalars(
                select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)
            )
        ).all()
    return ConversationDetail(**_c(c).model_dump(), messages=[_m(m) for m in messages])


@tenant_router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, request: Request, ctx: Ctx) -> Response:
    """Delete your own conversation and everything in it."""
    await check_permission(
        request,
        "conversation.messages.create",
        Resource(type="conversation", id=str(conversation_id)),
    )
    c = await _load(request, ctx, conversation_id, write=True)
    async with _db(request).session(ctx) as s:
        stored = await s.get(Conversation, c.id)
        if stored is not None:
            await s.delete(stored)
    return Response(status_code=204)


# ===================================================================== turns


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class ApprovalIn(BaseModel):
    approved: bool


async def _agent(
    request: Request, ctx: TenantContext, c: Conversation, payload: dict[str, Any]
) -> dict[str, Any]:
    client: httpx.AsyncClient = request.app.state.agent_client
    base = request.app.state.agent_url
    if base is None:
        raise ServiceUnavailable("Agent runtime URL is not configured")
    try:
        r = await client.post(
            f"{base}/v1/agents/{c.agent}/runs",
            json={"thread_id": str(c.id), "locale": c.locale, **payload},
            headers={CONTEXT_HEADER: str(request.state.context_token)},
        )
    except httpx.HTTPError as exc:
        raise ServiceUnavailable("The assistant is unreachable") from exc
    _agent_errors(r, c)
    result: dict[str, Any] = r.json()
    return result


def _agent_errors(r: httpx.Response, c: Conversation) -> None:
    if r.status_code in (401, 403):
        raise Forbidden("You may not talk to this assistant")
    if r.status_code == 404:
        raise NotFound(f"Assistant {c.agent!r} is not available")
    if r.status_code == 409:
        raise Conflict(str(r.json().get("detail")))
    if r.status_code >= 400:
        raise AgentFailed(
            str(
                r.json().get("detail")
                if r.headers.get("content-type", "").startswith("application")
                else r.text
            )[:300]
        )


async def _retention_days(request: Request, ctx: TenantContext, profile: str | None) -> int:
    default = int(request.app.state.settings.default_retention_days)
    if not profile:
        return default
    resolver: ProfileResolver = request.app.state.retention_profiles
    try:
        spec = await resolver.get(str(ctx.tenant_id), str(request.state.context_token), profile)
    except NexiqonError:
        return default
    return int(spec.get("conversations_days") or default)


async def _begin(
    request: Request, ctx: TenantContext, c: Conversation, user_text: str | None
) -> tuple[Message | None, list[dict[str, str]]]:
    """Store the user's message; returns it and the history to send to the agent."""
    db = _db(request)
    now = datetime.now(UTC)
    user_msg: Message | None = None
    async with db.session(ctx) as s:
        history_rows = (
            await s.scalars(
                select(Message)
                .where(Message.conversation_id == c.id)
                .order_by(Message.created_at.desc())
                .limit(request.app.state.settings.history_messages)
            )
        ).all()
        if user_text is not None:
            user_msg = Message(
                tenant_id=ctx.tenant_id,
                conversation_id=c.id,
                role="user",
                content=user_text,
                contract={},
            )
            s.add(user_msg)
            await s.flush()
            await s.refresh(user_msg)
        stored = await s.get(Conversation, c.id)
        assert stored is not None
        stored.last_message_at = now
        if stored.title is None and user_text:
            stored.title = user_text[:120]
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(history_rows)
        if m.role in ("user", "assistant")
    ]
    return user_msg, history


async def _quiet(
    request: Request, ctx: TenantContext, c: Conversation, user_msg: Message | None
) -> TurnOut:
    """A person has the conversation now; the assistant stays quiet."""
    return TurnOut(
        conversation=_c(await _load(request, ctx, c.id)),
        user_message=_m(user_msg) if user_msg else None,
        reply=None,
    )


async def _turn(
    request: Request,
    ctx: TenantContext,
    c: Conversation,
    user_text: str | None,
    payload: dict[str, Any],
) -> TurnOut:
    user_msg, history = await _begin(request, ctx, c, user_text)
    if c.status == "escalated":
        return await _quiet(request, ctx, c, user_msg)
    try:
        result = await _agent(request, ctx, c, {**payload, "history": history})
    except AgentFailed as exc:
        result = {"status": "failed", "error": exc.detail}
    return await _finish(request, ctx, c, user_msg, result)


async def _finish(
    request: Request,
    ctx: TenantContext,
    c: Conversation,
    user_msg: Message | None,
    result: dict[str, Any],
) -> TurnOut:
    """Store the assistant's reply (answer contract), conversation state and events."""
    db = _db(request)
    now = datetime.now(UTC)
    status = result.get("status")
    interrupt = result.get("interrupt") or {}
    if status == "completed":
        answer = result.get("answer") or {}
        text = str(answer.get("text") or "")
        contract = {
            **answer,
            "intent": result.get("intent"),
            "route": result.get("route"),
            "status": "completed",
        }
    elif status == "interrupted":
        text = str(interrupt.get("prompt") or "")
        contract = {
            "kind": interrupt.get("kind"),
            "interrupt": interrupt,
            "intent": result.get("intent"),
            "route": result.get("route"),
            "status": "interrupted",
        }
    else:
        text = FALLBACK.get(c.locale, FALLBACK["en"])
        contract = {"kind": "error", "status": "failed", "error": result.get("error")}
    handoff = result.get("handoff")
    days = await _retention_days(request, ctx, result.get("retention_profile"))
    async with db.session(ctx) as s:
        reply = Message(
            tenant_id=ctx.tenant_id,
            conversation_id=c.id,
            role="assistant",
            content=text,
            contract=contract,
            run_id=uuid.UUID(result["run_id"]) if result.get("run_id") else None,
        )
        s.add(reply)
        stored = await s.get(Conversation, c.id)
        assert stored is not None
        if status == "interrupted":
            stored.status = (
                "awaiting_approval" if interrupt.get("kind") == "approval" else "awaiting_input"
            )
        elif status == "completed":
            stored.status = "escalated" if handoff else "active"
        if handoff:
            stored.handoff_summary = str(handoff.get("summary") or "")[:4000]
        stored.retain_until = now + timedelta(days=days)
        await s.flush()
        await s.refresh(reply)
        common = {"conversation_id": str(c.id), "agent": c.agent, "channel": c.channel}
        if status == "completed":
            add_event(
                s,
                Outbox,
                ctx,
                source=SERVICE,
                type="nexiqon.conversation.turn.completed",
                subject=str(c.id),
                data={
                    **common,
                    "intent": result.get("intent"),
                    "route": result.get("route"),
                    "abstained": bool(contract.get("abstained")),
                    "citations": len(contract.get("citations") or []),
                },
            )
        if handoff:
            add_event(
                s,
                Outbox,
                ctx,
                source=SERVICE,
                type="nexiqon.conversation.escalated",
                subject=str(c.id),
                data={**common, "reason": handoff.get("reason")},
            )
        reply_out = _m(reply)
    return TurnOut(
        conversation=_c(await _load(request, ctx, c.id)),
        user_message=_m(user_msg) if user_msg else None,
        reply=reply_out,
    )


@tenant_router.post("/conversations/{conversation_id}/messages", response_model=TurnOut)
async def post_message(
    conversation_id: uuid.UUID, body: MessageIn, request: Request, ctx: Ctx
) -> TurnOut:
    """Send a message; the reply carries the answer contract (citations, abstained, route...)."""
    await check_permission(
        request,
        "conversation.messages.create",
        Resource(type="conversation", id=str(conversation_id)),
    )
    c = await _load(request, ctx, conversation_id, write=True)
    if c.status == "awaiting_approval":
        raise Conflict("Please approve or decline the pending action first")
    return await _turn(request, ctx, c, body.content, {"input": body.content})


@tenant_router.post("/conversations/{conversation_id}/approval", response_model=TurnOut)
async def approve(
    conversation_id: uuid.UUID, body: ApprovalIn, request: Request, ctx: Ctx
) -> TurnOut:
    """Approve or decline the action the assistant proposed."""
    await check_permission(
        request,
        "conversation.messages.create",
        Resource(type="conversation", id=str(conversation_id)),
    )
    c = await _load(request, ctx, conversation_id, write=True)
    if c.status != "awaiting_approval":
        raise BadRequest("Nothing is waiting for approval")
    return await _turn(request, ctx, c, None, {"resume": {"approved": body.approved}})


def _sse(kind: str, data: Any) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n".encode()


@tenant_router.post(
    "/conversations/{conversation_id}/messages/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_message(
    conversation_id: uuid.UUID, body: MessageIn, request: Request, ctx: Ctx
) -> StreamingResponse:
    """Send a message and receive the reply as server-sent events (CH-01): the agent's
    ``run``, ``status``, ``sources``, ``tool`` and ``delta`` events, then ``message`` with the
    stored turn (same shape as the non-streaming reply). The reply is stored even if the
    client disconnects mid-stream."""
    await check_permission(
        request,
        "conversation.messages.create",
        Resource(type="conversation", id=str(conversation_id)),
    )
    c = await _load(request, ctx, conversation_id, write=True)
    if c.status == "awaiting_approval":
        raise Conflict("Please approve or decline the pending action first")
    headers = {"cache-control": "no-store", "x-accel-buffering": "no"}
    user_msg, history = await _begin(request, ctx, c, body.content)
    if c.status == "escalated":
        quiet = await _quiet(request, ctx, c, user_msg)

        async def only() -> AsyncIterator[bytes]:
            yield _sse("message", quiet.model_dump(mode="json"))

        return StreamingResponse(only(), media_type="text/event-stream", headers=headers)
    client: httpx.AsyncClient = request.app.state.agent_client
    base = request.app.state.agent_url
    if base is None:
        raise ServiceUnavailable("Agent runtime URL is not configured")
    upstream = client.build_request(
        "POST",
        f"{base}/v1/agents/{c.agent}/runs/stream",
        json={
            "thread_id": str(c.id),
            "locale": c.locale,
            "input": body.content,
            "history": history,
        },
        headers={CONTEXT_HEADER: str(request.state.context_token)},
    )
    try:
        r = await client.send(upstream, stream=True)
    except httpx.HTTPError as exc:
        raise ServiceUnavailable("The assistant is unreachable") from exc
    if r.status_code >= 400:
        await r.aread()
        await r.aclose()
        _agent_errors(r, c)
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def relay() -> None:
        result: dict[str, Any] = {"status": "failed", "error": "The answer stream ended early"}
        try:
            event = "message"
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if event == "result":
                        result = data
                    elif event == "error":
                        result = {"status": "failed", "error": data.get("detail")}
                    else:
                        queue.put_nowait(_sse(event, data))
        except (httpx.HTTPError, ValueError):
            pass
        finally:
            await r.aclose()
        try:
            turn = await _finish(request, ctx, c, user_msg, result)
            queue.put_nowait(_sse("message", turn.model_dump(mode="json")))
        except NexiqonError as exc:
            queue.put_nowait(_sse("error", {"code": exc.code, "detail": exc.detail}))
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(relay())
    running: set[asyncio.Task[None]] = request.app.state.streams
    running.add(task)
    task.add_done_callback(running.discard)

    async def events() -> AsyncIterator[bytes]:
        while (item := await queue.get()) is not None:
            yield item

    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


@tenant_router.post("/conversations/{conversation_id}/handoff", response_model=TurnOut)
async def ask_for_person(conversation_id: uuid.UUID, request: Request, ctx: Ctx) -> TurnOut:
    """The user asks for a person (CV-02, widget handoff button): the assistant writes a summary
    and, when the pack names a handoff tool, offers to send it to the team."""
    await check_permission(
        request,
        "conversation.messages.create",
        Resource(type="conversation", id=str(conversation_id)),
    )
    c = await _load(request, ctx, conversation_id, write=True)
    if c.status == "escalated":
        raise Conflict("A person already has this conversation")
    if c.status == "awaiting_approval":
        raise Conflict("Please approve or decline the pending action first")
    text = ASK_FOR_PERSON.get(c.locale, ASK_FOR_PERSON["en"])
    return await _turn(request, ctx, c, text, {"input": text, "handoff": True})


# ===================================================================== feedback


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


@tenant_router.post("/messages/{message_id}/feedback", status_code=204)
async def feedback(message_id: uuid.UUID, body: FeedbackIn, request: Request, ctx: Ctx) -> Response:
    await check_permission(
        request, "conversation.messages.create", Resource(type="message", id=str(message_id))
    )
    async with _db(request).session(ctx) as s:
        message = await s.get(Message, message_id)
        if message is None or message.role != "assistant":
            raise NotFound("Message not found")
    await _load(request, ctx, message.conversation_id, write=True)
    async with _db(request).session(ctx) as s:
        s.add(
            Feedback(
                tenant_id=ctx.tenant_id,
                message_id=message_id,
                actor_id=ctx.actor_id,
                rating=body.rating,
                comment=body.comment,
            )
        )
        add_event(
            s,
            Outbox,
            ctx,
            source=SERVICE,
            type="nexiqon.conversation.feedback.given",
            subject=str(message_id),
            data={"message_id": str(message_id), "rating": body.rating},
        )
    return Response(status_code=204)
