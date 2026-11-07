"""Event consumer that appends every platform event to its tenant's audit chain."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from nexiqon_audit.chain import link, record
from nexiqon_audit.models import GENESIS, AuditEvent
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.tenancy import TenantContext


class Recorder:
    def __init__(self, sessions: TenantSessionFactory) -> None:
        self.sessions = sessions

    async def __call__(self, event: dict[str, Any]) -> None:
        tenant = uuid.UUID(str(event["nexiqontenantid"]))  # missing/invalid -> retried, then DLQ
        event_id = uuid.UUID(str(event["id"]))
        ctx = TenantContext(tenant_id=tenant, actor_id="service:audit", actor_type="service")
        async with self.sessions.session(ctx) as s:
            # Serialise appends per tenant so sequence numbers and the chain stay linear.
            await s.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:t, 7))"), {"t": str(tenant)}
            )
            if await s.scalar(select(AuditEvent.id).where(AuditEvent.event_id == event_id)):
                return  # redelivery: already recorded
            last = (
                await s.execute(
                    select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)
                )
            ).first()
            seq, prev = (last[0] + 1, last[1]) if last else (1, GENESIS)
            occurred = datetime.fromisoformat(str(event["time"]))
            data = event.get("data") or {}
            rec = record(
                seq=seq,
                event_id=str(event_id),
                type_=str(event["type"]),
                source=str(event["source"]),
                subject=event.get("subject"),
                actor_id=str(event.get("nexiqonactorid", "unknown")),
                occurred_at=occurred,
                data=data,
            )
            s.add(
                AuditEvent(
                    tenant_id=tenant,
                    seq=seq,
                    event_id=event_id,
                    type=rec["type"],
                    source=rec["source"],
                    subject=rec["subject"],
                    actor_id=rec["actor_id"],
                    occurred_at=occurred,
                    data=data,
                    traceparent=event.get("traceparent"),
                    prev_hash=prev,
                    hash=link(prev, rec),
                )
            )
