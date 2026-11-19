"""Turns platform events into metering's read models (MT-01). Idempotent: an event id is counted
once, in the same transaction as its counters, so redelivery never double-counts."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.events import add_event
from nexiqon_core.tenancy import TenantContext
from nexiqon_metering.models import (
    NO_AGENT,
    ActivityDaily,
    Budget,
    BudgetAlert,
    ConversationFacts,
    Outbox,
    Processed,
    UsageDaily,
)

log = structlog.get_logger(__name__)
SOURCE = "nexiqon/metering"
SUBJECTS = "nexiqon.>"
USAGE = "nexiqon.model-gateway.usage.recorded"


def _day(event: dict[str, Any]) -> date:
    try:
        return datetime.fromisoformat(str(event["time"])).astimezone(UTC).date()
    except (KeyError, ValueError):
        return datetime.now(UTC).date()


def month_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


async def bump(s: AsyncSession, ctx: TenantContext, day: date, agent: str, **metrics: int) -> None:
    for metric, n in metrics.items():
        if not n:
            continue
        stmt = insert(ActivityDaily).values(
            id=uuid.uuid4(), tenant_id=ctx.tenant_id, day=day, agent=agent, metric=metric, value=n
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=["tenant_id", "day", "agent", "metric"],
                set_={"value": ActivityDaily.value + n},
            )
        )


async def fact(
    s: AsyncSession, ctx: TenantContext, conversation: str, agent: str, day: date, **flags: Any
) -> None:
    """Create or update a conversation's facts; ``event`` adds to the kinds seen."""
    kind = flags.pop("event", None)
    row = await s.scalar(
        select(ConversationFacts).where(ConversationFacts.conversation_id == conversation)
    )
    if row is None:
        row = ConversationFacts(
            tenant_id=ctx.tenant_id,
            conversation_id=conversation,
            agent=agent,
            day=day,
            answered=False,
            escalated=False,
            rated_down=False,
            events=[],
        )
        s.add(row)
    for key, value in flags.items():
        if value:
            setattr(row, key, True)
    if kind and kind not in row.events:
        row.events = [*row.events, kind]


class Recorder:
    def __init__(self, db: TenantSessionFactory) -> None:
        self.db = db

    async def __call__(self, event: dict[str, Any]) -> None:
        kind = str(event.get("type", ""))
        tenant = uuid.UUID(str(event["nexiqontenantid"]))
        ctx = TenantContext(tenant_id=tenant, actor_id="service:metering", actor_type="service")
        data: dict[str, Any] = event.get("data") or {}
        day = _day(event)
        async with self.db.session(ctx) as s:
            claimed = await s.execute(
                insert(Processed)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    event_id=uuid.UUID(str(event["id"])),
                    type=kind,
                )
                .on_conflict_do_nothing(index_elements=["event_id"])
                .returning(Processed.id)
            )
            if claimed.first() is None:
                return  # already counted
            await self._apply(s, ctx, kind, data, day)

    async def _apply(
        self, s: AsyncSession, ctx: TenantContext, kind: str, data: dict[str, Any], day: date
    ) -> None:
        agent = str(data.get("agent") or NO_AGENT)
        conversation = data.get("conversation_id")
        short = kind.removeprefix("nexiqon.")
        if kind == USAGE:
            await self._usage(s, ctx, data, day, agent)
        elif short == "conversation.started" and conversation:
            await bump(s, ctx, day, agent, conversations=1)
            await fact(s, ctx, str(conversation), agent, day, event=short)
        elif short == "conversation.turn.completed" and conversation:
            answered = not data.get("abstained")
            await bump(
                s,
                ctx,
                day,
                agent,
                turns=1,
                answered=int(answered),
                unanswered=int(not answered),
                cited=int(answered and int(data.get("citations") or 0) > 0),
            )
            await fact(s, ctx, str(conversation), agent, day, answered=answered, event=short)
        elif short == "conversation.escalated" and conversation:
            await bump(s, ctx, day, agent, escalations=1)
            await fact(s, ctx, str(conversation), agent, day, escalated=True, event=short)
        elif short == "conversation.feedback.given":
            down = data.get("rating") == "down"
            await bump(s, ctx, day, agent, feedback_up=int(not down), feedback_down=int(down))
            if conversation:
                await fact(s, ctx, str(conversation), agent, day, rated_down=down, event=short)
        elif short == "tool-gateway.call.completed":
            await bump(s, ctx, day, agent, tool_calls=1, tool_errors=int(not data.get("ok")))
        elif conversation and short.startswith("conversation."):
            await fact(s, ctx, str(conversation), agent, day, event=short)

    async def _usage(
        self, s: AsyncSession, ctx: TenantContext, data: dict[str, Any], day: date, agent: str
    ) -> None:
        cost = Decimal(str(data.get("cost_usd") or "0"))
        values = {
            "id": uuid.uuid4(),
            "tenant_id": ctx.tenant_id,
            "day": day,
            "agent": agent,
            "operation": str(data.get("operation") or "chat"),
            "profile": str(data.get("profile") or ""),
            "provider": str(data.get("provider") or ""),
            "model": str(data.get("model") or ""),
            "calls": 1,
            "input_tokens": int(data.get("input_tokens") or 0),
            "output_tokens": int(data.get("output_tokens") or 0),
            "cost_usd": cost,
        }
        stmt = insert(UsageDaily).values(**values)
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    "tenant_id",
                    "day",
                    "agent",
                    "operation",
                    "profile",
                    "provider",
                    "model",
                ],
                set_={
                    "calls": UsageDaily.calls + 1,
                    "input_tokens": UsageDaily.input_tokens + values["input_tokens"],
                    "output_tokens": UsageDaily.output_tokens + values["output_tokens"],
                    "cost_usd": UsageDaily.cost_usd + cost,
                },
            )
        )
        if cost > 0:
            await check_budgets(s, ctx, day, agent)


async def month_spend(s: AsyncSession, day: date, agent: str | None) -> Decimal:
    start = day.replace(day=1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    q = select(func.coalesce(func.sum(UsageDaily.cost_usd), 0)).where(
        UsageDaily.day >= start, UsageDaily.day < end
    )
    if agent is not None:
        q = q.where(UsageDaily.agent == agent)
    return Decimal(str(await s.scalar(q) or 0))


async def check_budgets(s: AsyncSession, ctx: TenantContext, day: date, agent: str) -> None:
    """Record (once per month and threshold) each budget threshold the spend has reached."""
    await s.flush()
    budgets = list(await s.scalars(select(Budget).where(Budget.agent.in_([NO_AGENT, agent]))))
    month = month_of(day)
    for b in budgets:
        spent = await month_spend(s, day, None if b.agent == NO_AGENT else b.agent)
        for threshold in sorted(float(t) for t in b.thresholds or []):
            if spent < Decimal(str(threshold)) * b.monthly_usd:
                continue
            created = await s.execute(
                insert(BudgetAlert)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=ctx.tenant_id,
                    budget_id=b.id,
                    agent=b.agent,
                    month=month,
                    threshold=threshold,
                    spent_usd=spent,
                    limit_usd=b.monthly_usd,
                    extra={},
                )
                .on_conflict_do_nothing(index_elements=["budget_id", "month", "threshold"])
                .returning(BudgetAlert.id)
            )
            if created.first() is None:
                continue
            add_event(
                s,
                Outbox,
                ctx,
                source=SOURCE,
                type="nexiqon.metering.budget.threshold_reached",
                subject=f"budget/{b.agent or 'organization'}",
                data={
                    "agent": b.agent or None,
                    "month": month,
                    "threshold": threshold,
                    "spent_usd": str(spent),
                    "limit_usd": str(b.monthly_usd),
                },
            )
            log.info("budget_threshold_reached", agent=b.agent, threshold=threshold)
