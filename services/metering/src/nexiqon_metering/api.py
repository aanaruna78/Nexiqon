"""HTTP API for metering (MT-01, MT-02). Contract: contracts/openapi/metering.json.

* usage: tokens and cost per day, assistant, profile and model (matches model-gateway's records)
* budgets: monthly limits for the organization or one assistant, with threshold alerts
* insights: answer quality over time, the pack's KPIs, and content gaps
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import BadRequest, NotFound, ServiceUnavailable
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_metering.gaps import cluster
from nexiqon_metering.models import (
    NO_AGENT,
    ActivityDaily,
    Budget,
    BudgetAlert,
    ConversationFacts,
    UsageDaily,
)
from nexiqon_metering.recorder import month_spend

public_router = APIRouter(tags=["metering"])
tenant_router = APIRouter(prefix="/v1", tags=["metering"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
NAME = r"^[a-z0-9][a-z0-9-]{1,62}$"
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


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
        raise ServiceUnavailable("Metering storage is not configured")
    return db


async def _allow(request: Request, action: str, kind: str, rid: str | None = None) -> None:
    await check_permission(request, action, Resource(type=kind, id=rid))


def _month_range(month: str | None) -> tuple[str, date, date]:
    today = datetime.now(UTC).date()
    y, m = (int(month[:4]), int(month[5:7])) if month else (today.year, today.month)
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return f"{y:04d}-{m:02d}", start, end


# ===================================================================== usage (MT-01)


class UsageGroup(BaseModel):
    key: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str


class DayCost(BaseModel):
    day: date
    calls: int
    tokens: int
    cost_usd: str


class UsageSummary(BaseModel):
    month: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str
    by_agent: list[UsageGroup]
    by_model: list[UsageGroup]
    by_profile: list[UsageGroup]
    daily: list[DayCost]


@tenant_router.get("/usage/summary", response_model=UsageSummary)
async def usage_summary(
    request: Request,
    ctx: Ctx,
    month: Annotated[str | None, Query(pattern=MONTH)] = None,
    agent: Annotated[str | None, Query(pattern=NAME)] = None,
) -> UsageSummary:
    """A month's tokens and cost, by assistant, model and profile, with a daily series."""
    await _allow(request, "metering.usage.read", "usage")
    label, start, end = _month_range(month)
    async with _db(request).session(ctx) as s:
        q = select(UsageDaily).where(UsageDaily.day >= start, UsageDaily.day < end)
        if agent:
            q = q.where(UsageDaily.agent == agent)
        rows = list(await s.scalars(q))
    groups: dict[str, dict[str, list[Any]]] = {"agent": {}, "model": {}, "profile": {}}
    daily: dict[date, list[Any]] = defaultdict(lambda: [0, 0, Decimal(0)])
    for r in rows:
        keys = {
            "agent": r.agent or NO_AGENT,
            "model": f"{r.provider}/{r.model}",
            "profile": r.profile,
        }
        for g, key in keys.items():
            acc = groups[g].setdefault(key, [0, 0, 0, Decimal(0)])
            acc[0] += r.calls
            acc[1] += r.input_tokens
            acc[2] += r.output_tokens
            acc[3] += r.cost_usd
        d = daily[r.day]
        d[0] += r.calls
        d[1] += r.input_tokens + r.output_tokens
        d[2] += r.cost_usd

    def out(g: str) -> list[UsageGroup]:
        return sorted(
            (
                UsageGroup(
                    key=k, calls=v[0], input_tokens=v[1], output_tokens=v[2], cost_usd=str(v[3])
                )
                for k, v in groups[g].items()
            ),
            key=lambda u: -Decimal(u.cost_usd),
        )

    return UsageSummary(
        month=label,
        calls=sum(r.calls for r in rows),
        input_tokens=sum(r.input_tokens for r in rows),
        output_tokens=sum(r.output_tokens for r in rows),
        cost_usd=str(sum((r.cost_usd for r in rows), Decimal(0))),
        by_agent=out("agent"),
        by_model=out("model"),
        by_profile=out("profile"),
        daily=[
            DayCost(day=k, calls=v[0], tokens=v[1], cost_usd=str(v[2]))
            for k, v in sorted(daily.items())
        ],
    )


# ===================================================================== budgets and alerts


class BudgetIn(BaseModel):
    agent: str | None = Field(default=None, pattern=NAME)  # none = the whole organization
    monthly_usd: Decimal = Field(gt=0, le=Decimal("10000000"))
    thresholds: list[float] = Field(default_factory=lambda: [0.5, 0.8, 1.0], max_length=6)

    @field_validator("thresholds")
    @classmethod
    def _thresholds(cls, v: list[float]) -> list[float]:
        if any(t <= 0 or t > 2 for t in v):
            raise ValueError("thresholds are fractions of the budget, between 0 and 2")
        return sorted(set(v))


class BudgetOut(BaseModel):
    id: uuid.UUID
    agent: str | None
    monthly_usd: str
    thresholds: list[float]
    month: str
    spent_usd: str
    used: float  # spent / monthly_usd


async def _budget_out(s: Any, b: Budget, label: str, start: date) -> BudgetOut:
    spent = await month_spend(s, start, None if b.agent == NO_AGENT else b.agent)
    return BudgetOut(
        id=b.id,
        agent=b.agent or None,
        monthly_usd=str(b.monthly_usd),
        thresholds=[float(t) for t in b.thresholds],
        month=label,
        spent_usd=str(spent),
        used=round(float(spent / b.monthly_usd), 4) if b.monthly_usd else 0.0,
    )


@tenant_router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(
    request: Request, ctx: Ctx, month: Annotated[str | None, Query(pattern=MONTH)] = None
) -> list[BudgetOut]:
    await _allow(request, "metering.budgets.read", "budget")
    label, start, _ = _month_range(month)
    async with _db(request).session(ctx) as s:
        rows = list(await s.scalars(select(Budget).order_by(Budget.agent)))
        return [await _budget_out(s, b, label, start) for b in rows]


@tenant_router.put("/budgets", response_model=BudgetOut)
async def set_budget(body: BudgetIn, request: Request, ctx: Ctx) -> BudgetOut:
    """Create or change the budget for the organization or one assistant."""
    await _allow(request, "metering.budgets.write", "budget", body.agent)
    label, start, _ = _month_range(None)
    key = body.agent or NO_AGENT
    async with _db(request).session(ctx) as s:
        b = await s.scalar(select(Budget).where(Budget.agent == key))
        if b is None:
            b = Budget(tenant_id=ctx.tenant_id, agent=key)
            s.add(b)
        b.monthly_usd, b.thresholds = body.monthly_usd, body.thresholds
        await s.flush()
        return await _budget_out(s, b, label, start)


@tenant_router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(budget_id: uuid.UUID, request: Request, ctx: Ctx) -> Response:
    await _allow(request, "metering.budgets.write", "budget", str(budget_id))
    async with _db(request).session(ctx) as s:
        b = await s.get(Budget, budget_id)
        if b is None:
            raise NotFound("Budget not found")
        await s.delete(b)
    return Response(status_code=204)


class AlertOut(BaseModel):
    id: uuid.UUID
    agent: str | None
    month: str
    threshold: float
    spent_usd: str
    limit_usd: str
    created_at: datetime
    acknowledged_at: datetime | None


def _alert(a: BudgetAlert) -> AlertOut:
    return AlertOut(
        id=a.id,
        agent=a.agent or None,
        month=a.month,
        threshold=float(a.threshold),
        spent_usd=str(a.spent_usd),
        limit_usd=str(a.limit_usd),
        created_at=a.created_at,
        acknowledged_at=a.acknowledged_at,
    )


@tenant_router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(request: Request, ctx: Ctx, open_only: bool = False) -> list[AlertOut]:
    await _allow(request, "metering.budgets.read", "budget")
    async with _db(request).session(ctx) as s:
        q = select(BudgetAlert).order_by(BudgetAlert.created_at.desc()).limit(100)
        if open_only:
            q = q.where(BudgetAlert.acknowledged_at.is_(None))
        return [_alert(a) for a in await s.scalars(q)]


@tenant_router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge(alert_id: uuid.UUID, request: Request, ctx: Ctx) -> AlertOut:
    await _allow(request, "metering.budgets.write", "budget", str(alert_id))
    async with _db(request).session(ctx) as s:
        a = await s.get(BudgetAlert, alert_id)
        if a is None:
            raise NotFound("Alert not found")
        a.acknowledged_at = a.acknowledged_at or datetime.now(UTC)
        await s.flush()
        return _alert(a)


# ===================================================================== insights (MT-02)

METRICS = (
    "conversations",
    "turns",
    "answered",
    "unanswered",
    "cited",
    "escalations",
    "feedback_up",
    "feedback_down",
    "tool_calls",
    "tool_errors",
)


def rates(t: dict[str, int]) -> dict[str, float | None]:
    def div(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    return {
        "answer_rate": div(t["answered"], t["turns"]),
        "citation_rate": div(t["cited"], t["answered"]),
        "escalation_rate": div(t["escalations"], t["conversations"]),
        "satisfaction": div(t["feedback_up"], t["feedback_up"] + t["feedback_down"]),
        "tool_error_rate": div(t["tool_errors"], t["tool_calls"]),
    }


class DayActivity(BaseModel):
    day: date
    metrics: dict[str, int]


class Quality(BaseModel):
    days: int
    agent: str | None
    totals: dict[str, int]
    rates: dict[str, float | None]
    previous_rates: dict[str, float | None]  # the same length of time just before
    daily: list[DayActivity]


@tenant_router.get("/insights/quality", response_model=Quality)
async def quality(
    request: Request,
    ctx: Ctx,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    agent: Annotated[str | None, Query(pattern=NAME)] = None,
) -> Quality:
    """Answer rate, citations, handoffs, satisfaction and tool errors over time."""
    await _allow(request, "metering.insights.read", "insights", agent)
    today = datetime.now(UTC).date()
    since, before = today - timedelta(days=days - 1), today - timedelta(days=2 * days - 1)
    async with _db(request).session(ctx) as s:
        q = select(ActivityDaily).where(ActivityDaily.day >= before)
        if agent:
            q = q.where(ActivityDaily.agent == agent)
        rows = list(await s.scalars(q))
    now_t = dict.fromkeys(METRICS, 0)
    prev_t = dict.fromkeys(METRICS, 0)
    daily: dict[date, dict[str, int]] = defaultdict(lambda: dict.fromkeys(METRICS, 0))
    for r in rows:
        if r.metric not in now_t:
            continue
        if r.day >= since:
            now_t[r.metric] += r.value
            daily[r.day][r.metric] += r.value
        else:
            prev_t[r.metric] += r.value
    return Quality(
        days=days,
        agent=agent,
        totals=now_t,
        rates=rates(now_t),
        previous_rates=rates(prev_t),
        daily=[DayActivity(day=d, metrics=m) for d, m in sorted(daily.items())],
    )


class Kpi(BaseModel):
    name: str
    description: str
    event: str
    value: float | None
    count: int
    conversations: int


RESOLVED = "conversation.resolved"  # derived: answered and never handed over


@tenant_router.get("/insights/kpis", response_model=list[Kpi])
async def kpis(
    request: Request,
    ctx: Ctx,
    agent: Annotated[str, Query(pattern=NAME)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[Kpi]:
    """The pack's own KPIs (``analytics.kpis``): the share of conversations in which an event
    happened. ``conversation.resolved`` means answered and never handed to a person."""
    await _allow(request, "metering.insights.read", "insights", agent)
    defined = await request.app.state.peers.kpis(ctx.tenant_id, agent)
    since = datetime.now(UTC).date() - timedelta(days=days - 1)
    async with _db(request).session(ctx) as s:
        facts = list(
            await s.scalars(
                select(ConversationFacts).where(
                    ConversationFacts.agent == agent, ConversationFacts.day >= since
                )
            )
        )
    total = len(facts)
    out = []
    for k in defined:
        event = str(k.get("event") or "")
        if event == RESOLVED:
            count = sum(1 for f in facts if f.answered and not f.escalated)
        else:
            count = sum(1 for f in facts if event in (f.events or []))
        out.append(
            Kpi(
                name=str(k.get("name")),
                description=str(k.get("description") or ""),
                event=event,
                value=round(count / total, 4) if total else None,
                count=count,
                conversations=total,
            )
        )
    return out


class GapTopic(BaseModel):
    label: list[str]
    count: int
    reasons: dict[str, int]
    example: str
    examples: list[str]
    conversations: list[str]


class GapReport(BaseModel):
    days: int
    agent: str | None
    questions: int
    topics: list[GapTopic]


@tenant_router.get("/insights/gaps", response_model=GapReport)
async def gaps(
    request: Request,
    ctx: Ctx,
    agent: Annotated[str | None, Query(pattern=NAME)] = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> GapReport:
    """What people asked that the knowledge does not answer, grouped into topics (UX G3).
    The questions are visitors' own words, so this needs ``metering.gaps.view``."""
    await _allow(request, "metering.gaps.view", "insights", agent)
    questions = await request.app.state.peers.gap_questions(ctx.tenant_id, agent, days)
    if len(questions) > 5000:
        raise BadRequest("Too many questions; narrow it to one assistant or fewer days")
    topics = cluster(questions, threshold=request.app.state.settings.gap_similarity)
    return GapReport(
        days=days, agent=agent, questions=len(questions), topics=[GapTopic(**t) for t in topics]
    )


@tenant_router.get("/insights/agents", response_model=list[str])
async def active_agents(request: Request, ctx: Ctx) -> list[str]:
    """Assistants with any recorded activity or usage."""
    await _allow(request, "metering.insights.read", "insights")
    async with _db(request).session(ctx) as s:
        a = set(await s.scalars(select(func.distinct(ActivityDaily.agent))))
        u = set(await s.scalars(select(func.distinct(UsageDaily.agent))))
    return sorted(x for x in a | u if x)
