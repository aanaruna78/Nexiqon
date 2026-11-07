"""HTTP API for audit. Contract: contracts/openapi/audit.json."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from nexiqon_audit.chain import link, record
from nexiqon_audit.models import GENESIS, AuditEvent
from nexiqon_core.authz import require_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import ServiceUnavailable
from nexiqon_core.tenancy import TenantContext, require_current_context

public_router = APIRouter(tags=["audit"])
tenant_router = APIRouter(prefix="/v1", tags=["audit"])
Ctx = Annotated[TenantContext, Depends(require_current_context)]


def _db(request: Request) -> TenantSessionFactory:
    db: TenantSessionFactory | None = request.app.state.db
    if db is None:
        raise ServiceUnavailable("Audit database is not configured")
    return db


class AuditEventOut(BaseModel):
    seq: int
    event_id: UUID
    type: str
    source: str
    subject: str | None
    actor_id: str
    occurred_at: datetime
    data: dict[str, Any]
    trace_id: str | None
    hash: str


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    next_before_seq: int | None


@tenant_router.get(
    "/events",
    response_model=AuditPage,
    dependencies=[require_permission("audit.events.read", "audit_event")],
)
async def list_events(
    request: Request,
    ctx: Ctx,
    type: str | None = None,
    actor_id: str | None = None,
    subject: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_seq: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    """Newest first. Filter by event type (prefix with '*' suffix), actor, subject or time."""
    stmt = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit + 1)
    if type:
        stmt = stmt.where(
            AuditEvent.type.startswith(type[:-1]) if type.endswith("*") else AuditEvent.type == type
        )
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if subject:
        stmt = stmt.where(AuditEvent.subject == subject)
    if since:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditEvent.occurred_at < until)
    if before_seq:
        stmt = stmt.where(AuditEvent.seq < before_seq)
    async with _db(request).session(ctx) as s:
        rows = list((await s.scalars(stmt)).all())
    page, more = rows[:limit], len(rows) > limit
    return AuditPage(
        items=[
            AuditEventOut(
                seq=r.seq,
                event_id=r.event_id,
                type=r.type,
                source=r.source,
                subject=r.subject,
                actor_id=r.actor_id,
                occurred_at=r.occurred_at,
                data=r.data,
                trace_id=r.traceparent.split("-")[1] if r.traceparent else None,
                hash=r.hash,
            )
            for r in page
        ],
        next_before_seq=page[-1].seq if more and page else None,
    )


class Verification(BaseModel):
    ok: bool
    length: int
    head: str
    first_broken_seq: int | None = None


@tenant_router.get(
    "/verify",
    response_model=Verification,
    dependencies=[require_permission("audit.chain.verify", "audit_event")],
)
async def verify_chain(request: Request, ctx: Ctx) -> Verification:
    """Recompute the tenant's whole chain from genesis."""
    prev, expected_seq, count = GENESIS, 1, 0
    async with _db(request).session(ctx) as s:
        result = await s.stream_scalars(select(AuditEvent).order_by(AuditEvent.seq))
        async for r in result:
            rec = record(
                seq=r.seq,
                event_id=str(r.event_id),
                type_=r.type,
                source=r.source,
                subject=r.subject,
                actor_id=r.actor_id,
                occurred_at=r.occurred_at,
                data=r.data,
            )
            if r.seq != expected_seq or r.prev_hash != prev or r.hash != link(prev, rec):
                return Verification(ok=False, length=count, head=prev, first_broken_seq=r.seq)
            prev, expected_seq, count = r.hash, expected_seq + 1, count + 1
    return Verification(ok=True, length=count, head=prev)
