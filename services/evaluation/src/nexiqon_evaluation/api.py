"""HTTP API for evaluation (QA-01, QA-02). Contract: contracts/openapi/evaluation.json.

* test sets and their cases (from a pack's gold set, from conversations, or written by hand)
* runs: ask one assistant version every case, scored by evaluator plugins (Temporal)
* reports: the latest scorecard per version
* gates: may this version be published? (asked by config on publish)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select, update

from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import BadRequest, Conflict, NotFound, ServiceUnavailable
from nexiqon_core.events import add_event
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_core.workflows import TenantScope, workflow_id
from nexiqon_evaluation.models import EvalResult, EvalRun, EvalSet, EvalSetCase, Outbox
from nexiqon_evaluation.scoring import Thresholds, gate
from nexiqon_sdk import Manifest, PluginKind

public_router = APIRouter(tags=["evaluation"])
tenant_router = APIRouter(prefix="/v1", tags=["evaluation"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
NAME = r"^[a-z0-9][a-z0-9-]{1,62}$"
SOURCE = "nexiqon/evaluation"


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
        raise ServiceUnavailable("Evaluation storage is not configured")
    return db


async def _allow(request: Request, action: str, kind: str, rid: str | None = None) -> None:
    await check_permission(request, action, Resource(type=kind, id=rid))


def _event(s: Any, ctx: TenantContext, type_: str, subject: str, **data: Any) -> None:
    add_event(
        s,
        Outbox,
        ctx,
        source=SOURCE,
        type=f"nexiqon.evaluation.{type_}",
        subject=subject,
        data=data,
    )


# ===================================================================== evaluators


@tenant_router.get("/evaluators", response_model=list[Manifest])
async def evaluators(request: Request, ctx: Ctx) -> list[Manifest]:
    await _allow(request, "evaluation.evaluators.read", "evaluator")
    manifests: list[Manifest] = request.app.state.registry.manifests(PluginKind.EVALUATOR)
    return manifests


# ===================================================================== test sets

Text = Annotated[str, Field(min_length=1, max_length=500)]


class CaseIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    lang: str = Field(default="en", pattern=r"^[a-z]{2}$")
    expected_source: str | None = Field(default=None, max_length=500)
    expected_section: str | None = Field(default=None, max_length=500)
    expected_phrases: list[Text] = Field(default_factory=list, max_length=10)
    must_abstain: bool = False
    origin: dict[str, str] = Field(default_factory=dict, max_length=5)
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _expectation(self) -> CaseIn:
        if self.must_abstain and (self.expected_phrases or self.expected_source):
            raise ValueError("a case the sources do not answer cannot expect facts or a source")
        return self


class CaseOut(CaseIn):
    id: uuid.UUID
    created_at: datetime


class SetIn(BaseModel):
    name: str = Field(pattern=NAME)
    agent: str | None = Field(default=None, pattern=NAME)
    description: str = Field(default="", max_length=1000)
    evaluators: list[Annotated[str, Field(pattern=NAME)]] = Field(default_factory=list)
    cases: list[CaseIn] = Field(default_factory=list, max_length=500)


class SetPatch(BaseModel):
    agent: str | None = Field(default=None, pattern=NAME)
    description: str | None = Field(default=None, max_length=1000)
    evaluators: list[Annotated[str, Field(pattern=NAME)]] | None = None


class SetOut(BaseModel):
    id: uuid.UUID
    name: str
    agent: str | None
    description: str
    origin: str
    evaluators: list[str]
    revision: int
    case_count: int
    created_at: datetime
    updated_at: datetime


def _case_out(c: EvalSetCase) -> CaseOut:
    return CaseOut.model_validate(c, from_attributes=True)


async def _set_out(s: Any, t: EvalSet) -> SetOut:
    count = await s.scalar(
        select(func.count()).select_from(EvalSetCase).where(EvalSetCase.test_set_id == t.id)
    )
    return SetOut(
        id=t.id,
        name=t.name,
        agent=t.agent,
        description=t.description,
        origin=t.origin,
        evaluators=list(t.evaluators or []),
        revision=t.revision,
        case_count=int(count or 0),
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


async def _get_set(s: Any, set_id: uuid.UUID) -> EvalSet:
    t: EvalSet | None = await s.get(EvalSet, set_id)
    if t is None:
        raise NotFound("Test set not found")
    return t


def _check_evaluators(request: Request, names: list[str]) -> None:
    known = {m.name for m in request.app.state.registry.manifests(PluginKind.EVALUATOR)}
    unknown = sorted(set(names) - known)
    if unknown:
        raise BadRequest(f"Unknown evaluators: {', '.join(unknown)}")


async def _add_cases(
    request: Request, s: Any, ctx: TenantContext, t: EvalSet, cases: list[CaseIn]
) -> list[EvalSetCase]:
    current = await s.scalar(
        select(func.count()).select_from(EvalSetCase).where(EvalSetCase.test_set_id == t.id)
    )
    if int(current or 0) + len(cases) > request.app.state.settings.max_cases:
        raise BadRequest(f"A test set holds at most {request.app.state.settings.max_cases} cases")
    rows = [EvalSetCase(tenant_id=ctx.tenant_id, test_set_id=t.id, **c.model_dump()) for c in cases]
    s.add_all(rows)
    t.revision += 1
    await s.flush()
    return rows


async def _create_set(request: Request, ctx: TenantContext, body: SetIn, origin: str) -> SetOut:
    _check_evaluators(request, body.evaluators)
    async with _db(request).session(ctx) as s:
        if await s.scalar(select(EvalSet.id).where(EvalSet.name == body.name)):
            raise Conflict(f"A test set named {body.name!r} exists")
        t = EvalSet(
            tenant_id=ctx.tenant_id,
            name=body.name,
            agent=body.agent,
            description=body.description,
            origin=origin,
            evaluators=body.evaluators,
            revision=0,
        )
        s.add(t)
        await s.flush()
        await _add_cases(request, s, ctx, t, body.cases)
        _event(s, ctx, "test_set.created", f"test_set/{t.name}", cases=len(body.cases))
        return await _set_out(s, t)


@tenant_router.get("/test-sets", response_model=list[SetOut])
async def list_sets(request: Request, ctx: Ctx, agent: str | None = None) -> list[SetOut]:
    await _allow(request, "evaluation.test_sets.read", "test_set")
    async with _db(request).session(ctx) as s:
        q = select(EvalSet).order_by(EvalSet.name)
        if agent:
            q = q.where((EvalSet.agent == agent) | (EvalSet.agent.is_(None)))
        return [await _set_out(s, t) for t in await s.scalars(q)]


@tenant_router.post("/test-sets", response_model=SetOut, status_code=201)
async def create_set(body: SetIn, request: Request, ctx: Ctx) -> SetOut:
    await _allow(request, "evaluation.test_sets.write", "test_set", body.name)
    origin = "conversations" if any(c.origin for c in body.cases) else "manual"
    return await _create_set(request, ctx, body, origin)


class PackSetIn(BaseModel):
    pack: str = Field(pattern=NAME)
    name: str | None = Field(default=None, pattern=NAME)
    agent: str | None = Field(default=None, pattern=NAME)


def pack_cases(path: Path) -> list[CaseIn]:
    """A pack's gold set (eval/gold.yaml) as test cases: expected source, section and evidence,
    plus the questions its documents do not answer."""
    data = yaml.safe_load(path.read_text()) or {}
    cases = [
        CaseIn(
            question=str(c["q"]),
            lang=str(c.get("lang") or "en"),
            expected_source=c.get("doc"),
            expected_section=c.get("section"),
            expected_phrases=[str(c["evidence"])] if c.get("evidence") else [],
            origin={"kind": "pack"},
        )
        for c in data.get("cases") or []
    ]
    cases += [
        CaseIn(
            question=str(c["q"]),
            lang=str(c.get("lang") or "en"),
            must_abstain=True,
            origin={"kind": "pack"},
        )
        for c in data.get("unanswerable") or []
    ]
    return cases


@tenant_router.post("/test-sets/from-pack", response_model=SetOut, status_code=201)
async def set_from_pack(body: PackSetIn, request: Request, ctx: Ctx) -> SetOut:
    """Start from the ready-made questions a Domain Pack ships with."""
    name = body.name or f"{body.pack}-gold"
    await _allow(request, "evaluation.test_sets.write", "test_set", name)
    path = Path(request.app.state.settings.pack_gallery_dir) / body.pack / "eval" / "gold.yaml"
    if not path.is_file():
        raise NotFound(f"Pack {body.pack!r} has no evaluation set")
    cases = pack_cases(path)
    desc = f"Questions shipped with the {body.pack} pack"
    return await _create_set(
        request, ctx, SetIn(name=name, agent=body.agent, description=desc, cases=cases), "pack"
    )


@tenant_router.get("/test-sets/{set_id}", response_model=SetOut)
async def get_set(set_id: uuid.UUID, request: Request, ctx: Ctx) -> SetOut:
    await _allow(request, "evaluation.test_sets.read", "test_set", str(set_id))
    async with _db(request).session(ctx) as s:
        return await _set_out(s, await _get_set(s, set_id))


@tenant_router.patch("/test-sets/{set_id}", response_model=SetOut)
async def patch_set(set_id: uuid.UUID, body: SetPatch, request: Request, ctx: Ctx) -> SetOut:
    await _allow(request, "evaluation.test_sets.write", "test_set", str(set_id))
    if body.evaluators is not None:
        _check_evaluators(request, body.evaluators)
    async with _db(request).session(ctx) as s:
        t = await _get_set(s, set_id)
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(t, key, value)
        if body.evaluators is not None:
            t.revision += 1  # what counts as passing changed: earlier runs no longer prove it
        await s.flush()
        return await _set_out(s, t)


@tenant_router.delete("/test-sets/{set_id}", status_code=204)
async def delete_set(set_id: uuid.UUID, request: Request, ctx: Ctx) -> Response:
    await _allow(request, "evaluation.test_sets.write", "test_set", str(set_id))
    async with _db(request).session(ctx) as s:
        t = await _get_set(s, set_id)
        _event(s, ctx, "test_set.deleted", f"test_set/{t.name}")
        await s.delete(t)
    return Response(status_code=204)


@tenant_router.get("/test-sets/{set_id}/cases", response_model=list[CaseOut])
async def list_cases(set_id: uuid.UUID, request: Request, ctx: Ctx) -> list[CaseOut]:
    # Expected answers quote the knowledge: only people who build assistants see them.
    await _allow(request, "evaluation.cases.view", "test_set", str(set_id))
    async with _db(request).session(ctx) as s:
        await _get_set(s, set_id)
        rows = await s.scalars(
            select(EvalSetCase)
            .where(EvalSetCase.test_set_id == set_id)
            .order_by(EvalSetCase.created_at, EvalSetCase.id)
        )
        return [_case_out(c) for c in rows]


@tenant_router.post("/test-sets/{set_id}/cases", response_model=list[CaseOut], status_code=201)
async def add_cases(
    set_id: uuid.UUID, body: list[CaseIn], request: Request, ctx: Ctx
) -> list[CaseOut]:
    """Add cases, e.g. a bad answer turned into a regression case (fix loop, ST-14)."""
    await _allow(request, "evaluation.test_sets.write", "test_set", str(set_id))
    if not body or len(body) > 500:
        raise BadRequest("Send between 1 and 500 cases")
    async with _db(request).session(ctx) as s:
        rows = await _add_cases(request, s, ctx, await _get_set(s, set_id), body)
        return [_case_out(c) for c in rows]


@tenant_router.put("/test-sets/{set_id}/cases/{case_id}", response_model=CaseOut)
async def replace_case(
    set_id: uuid.UUID, case_id: uuid.UUID, body: CaseIn, request: Request, ctx: Ctx
) -> CaseOut:
    await _allow(request, "evaluation.test_sets.write", "test_set", str(set_id))
    async with _db(request).session(ctx) as s:
        t = await _get_set(s, set_id)
        c = await s.get(EvalSetCase, case_id)
        if c is None or c.test_set_id != set_id:
            raise NotFound("Case not found")
        for key, value in body.model_dump().items():
            setattr(c, key, value)
        t.revision += 1
        await s.flush()
        return _case_out(c)


@tenant_router.delete("/test-sets/{set_id}/cases/{case_id}", status_code=204)
async def delete_case(
    set_id: uuid.UUID, case_id: uuid.UUID, request: Request, ctx: Ctx
) -> Response:
    await _allow(request, "evaluation.test_sets.write", "test_set", str(set_id))
    async with _db(request).session(ctx) as s:
        t = await _get_set(s, set_id)
        result = await s.execute(
            delete(EvalSetCase).where(EvalSetCase.id == case_id, EvalSetCase.test_set_id == set_id)
        )
        if not result.rowcount:  # type: ignore[attr-defined]
            raise NotFound("Case not found")
        t.revision += 1
    return Response(status_code=204)


# ===================================================================== runs


class RunIn(BaseModel):
    agent: str = Field(pattern=NAME)
    version: int = Field(ge=1)
    test_set_id: uuid.UUID


class RunOut(BaseModel):
    id: uuid.UUID
    agent: str
    version: int
    test_set_id: uuid.UUID
    test_set_revision: int
    spec_hash: str
    current: bool  # made on the test set's current cases
    status: str
    started_by: str
    case_count: int
    done_count: int
    scorecard: dict[str, Any] | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


def _run_out(r: EvalRun, revision: int | None) -> RunOut:
    return RunOut(
        id=r.id,
        agent=r.agent,
        version=r.version,
        test_set_id=r.test_set_id,
        test_set_revision=r.test_set_revision,
        spec_hash=r.spec_hash,
        current=revision is not None and r.test_set_revision == revision,
        status=r.status,
        started_by=r.started_by,
        case_count=r.case_count,
        done_count=r.done_count,
        scorecard=r.scorecard,
        error=r.error,
        created_at=r.created_at,
        finished_at=r.finished_at,
    )


async def _revisions(s: Any) -> dict[uuid.UUID, int]:
    return {i: rev for i, rev in (await s.execute(select(EvalSet.id, EvalSet.revision))).all()}


@tenant_router.post("/runs", response_model=RunOut, status_code=202)
async def start_run(body: RunIn, request: Request, ctx: Ctx) -> RunOut:
    """Evaluate one version of an assistant (drafts too) on a test set."""
    await _allow(request, "evaluation.runs.write", "agent", body.agent)
    temporal = request.app.state.temporal
    if temporal is None:
        raise ServiceUnavailable("Evaluation runs need the workflow engine")
    settings = request.app.state.settings
    digest = await request.app.state.config_client.spec_hash(
        request.app.state.tokens.for_tenant(ctx.tenant_id), body.agent, body.version
    )
    if digest is None:
        raise NotFound(f"Assistant {body.agent!r} has no version {body.version}")
    async with _db(request).session(ctx) as s:
        t = await _get_set(s, body.test_set_id)
        cases = await s.scalar(
            select(func.count()).select_from(EvalSetCase).where(EvalSetCase.test_set_id == t.id)
        )
        if not cases:
            raise BadRequest("The test set has no cases")
        running = await s.scalar(
            select(EvalRun.id).where(
                EvalRun.agent == body.agent,
                EvalRun.version == body.version,
                EvalRun.test_set_id == t.id,
                EvalRun.test_set_revision == t.revision,
                EvalRun.spec_hash == digest,
                EvalRun.status.in_(["queued", "running"]),
            )
        )
        if running is not None:
            raise Conflict("This version is already being evaluated on these cases")
        run = EvalRun(
            tenant_id=ctx.tenant_id,
            agent=body.agent,
            version=body.version,
            test_set_id=t.id,
            test_set_revision=t.revision,
            spec_hash=digest,
            status="queued",
            started_by=ctx.actor_id,
            case_count=int(cases),
            done_count=0,
        )
        s.add(run)
        await s.flush()
        _event(
            s, ctx, "run.started", f"agent/{body.agent}", run_id=str(run.id), version=body.version
        )
        out = _run_out(run, t.revision)
    scope = TenantScope.of(ctx)
    await temporal.start_workflow(
        "evaluation.RunEvaluation",
        args=[scope, str(out.id), settings.concurrency, settings.case_timeout_seconds],
        id=workflow_id(scope, "evaluation", str(out.id)),
        task_queue=settings.task_queue,
    )
    return out


@tenant_router.get("/runs", response_model=list[RunOut])
async def list_runs(
    request: Request,
    ctx: Ctx,
    agent: str | None = None,
    test_set_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunOut]:
    await _allow(request, "evaluation.runs.read", "agent", agent)
    async with _db(request).session(ctx) as s:
        q = select(EvalRun).order_by(EvalRun.created_at.desc(), EvalRun.id.desc()).limit(limit)
        if agent:
            q = q.where(EvalRun.agent == agent)
        if test_set_id:
            q = q.where(EvalRun.test_set_id == test_set_id)
        revisions = await _revisions(s)
        return [_run_out(r, revisions.get(r.test_set_id)) for r in await s.scalars(q)]


@tenant_router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, request: Request, ctx: Ctx) -> RunOut:
    await _allow(request, "evaluation.runs.read", "evaluation_run", str(run_id))
    async with _db(request).session(ctx) as s:
        r = await s.get(EvalRun, run_id)
        if r is None:
            raise NotFound("Run not found")
        return _run_out(r, (await _revisions(s)).get(r.test_set_id))


class ResultOut(BaseModel):
    case_id: uuid.UUID
    question: str
    lang: str
    answer: str
    abstained: bool
    kind: str | None
    citations: list[dict[str, Any]]
    scores: dict[str, Any]
    passed: bool
    latency_ms: int
    tokens: int
    cost: float
    agent_run_id: str | None
    error: str | None


@tenant_router.get("/runs/{run_id}/results", response_model=list[ResultOut])
async def run_results(
    run_id: uuid.UUID,
    request: Request,
    ctx: Ctx,
    outcome: Literal["all", "failed", "passed"] = "all",
) -> list[ResultOut]:
    """Per-case answers and scores. Answers were made with a content manager's view of the
    knowledge, so only people who build assistants may read them."""
    await _allow(request, "evaluation.results.view", "evaluation_run", str(run_id))
    async with _db(request).session(ctx) as s:
        if await s.get(EvalRun, run_id) is None:
            raise NotFound("Run not found")
        q = select(EvalResult).where(EvalResult.run_id == run_id)
        if outcome != "all":
            q = q.where(EvalResult.passed.is_(outcome == "passed"))
        rows = await s.scalars(q.order_by(EvalResult.passed, EvalResult.created_at))
        return [ResultOut.model_validate(r, from_attributes=True) for r in rows]


@tenant_router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: uuid.UUID, request: Request, ctx: Ctx) -> RunOut:
    await _allow(request, "evaluation.runs.write", "evaluation_run", str(run_id))
    async with _db(request).session(ctx) as s:
        r = await s.get(EvalRun, run_id)
        if r is None:
            raise NotFound("Run not found")
        if r.status not in ("queued", "running"):
            raise Conflict("The run has finished")
        temporal = request.app.state.temporal
        if temporal is not None:
            handle = temporal.get_workflow_handle(
                workflow_id(TenantScope.of(ctx), "evaluation", str(run_id))
            )
            await handle.cancel()
        await s.execute(
            update(EvalRun).where(EvalRun.id == run_id).values(status="failed", error="cancelled")
        )
        await s.refresh(r)
        return _run_out(r, (await _revisions(s)).get(r.test_set_id))


# ===================================================================== reports


class ReportRow(BaseModel):
    agent: str
    version: int
    test_set_id: uuid.UUID
    test_set: str
    run_id: uuid.UUID
    current: bool
    scorecard: dict[str, Any]
    finished_at: datetime | None


async def _latest(
    s: Any, agent: str, version: int, test_set_id: uuid.UUID, spec_hash: str | None = None
) -> EvalRun | None:
    q = select(EvalRun).where(
        EvalRun.agent == agent,
        EvalRun.version == version,
        EvalRun.test_set_id == test_set_id,
        EvalRun.status == "completed",
    )
    if spec_hash is not None:
        q = q.where(EvalRun.spec_hash == spec_hash)
    run: EvalRun | None = await s.scalar(
        q.order_by(EvalRun.finished_at.desc(), EvalRun.id.desc()).limit(1)
    )
    return run


@tenant_router.get("/evaluations/reports", response_model=list[ReportRow])
async def reports(
    request: Request,
    ctx: Ctx,
    agent: Annotated[str, Query(pattern=NAME)],
    test_set_id: uuid.UUID | None = None,
) -> list[ReportRow]:
    """The latest completed scorecard per version and test set (newest version first)."""
    await _allow(request, "evaluation.runs.read", "agent", agent)
    async with _db(request).session(ctx) as s:
        q = select(EvalRun).where(EvalRun.agent == agent, EvalRun.status == "completed")
        if test_set_id:
            q = q.where(EvalRun.test_set_id == test_set_id)
        sets = {t.id: t for t in await s.scalars(select(EvalSet))}
        latest: dict[tuple[int, uuid.UUID], EvalRun] = {}
        for r in await s.scalars(q.order_by(EvalRun.finished_at, EvalRun.id)):
            latest[(r.version, r.test_set_id)] = r
        return [
            ReportRow(
                agent=r.agent,
                version=r.version,
                test_set_id=r.test_set_id,
                test_set=sets[r.test_set_id].name,
                run_id=r.id,
                current=r.test_set_revision == sets[r.test_set_id].revision,
                scorecard=r.scorecard or {},
                finished_at=r.finished_at,
            )
            for (_, set_id), r in sorted(latest.items(), key=lambda kv: -kv[0][0])
            if set_id in sets
        ]


# ===================================================================== release gate (QA-02)


class GateIn(BaseModel):
    version: int = Field(ge=1)
    # The content being published: runs of other content (an earlier draft) do not count.
    spec_hash: str | None = Field(default=None, max_length=64)
    baseline_version: int | None = Field(default=None, ge=1)
    test_set: str = Field(pattern=NAME)
    min_pass_rate: float | None = Field(default=None, ge=0, le=1)
    max_drop: float | None = Field(default=None, ge=0, le=1)


class GateOut(BaseModel):
    passed: bool
    reasons: list[dict[str, Any]]
    deltas: dict[str, float]
    test_set_id: uuid.UUID | None
    run_id: uuid.UUID | None
    baseline_run_id: uuid.UUID | None
    scorecard: dict[str, Any] | None
    baseline_scorecard: dict[str, Any] | None
    thresholds: dict[str, float]


@tenant_router.post("/gates/agents/{agent}/check", response_model=GateOut)
async def check_gate(
    agent: Annotated[str, Field(pattern=NAME)], body: GateIn, request: Request, ctx: Ctx
) -> GateOut:
    """May ``version`` replace ``baseline_version``? Needs a completed run on the test set's
    current cases that clears the pass rate and does not fall behind the live version."""
    await _allow(request, "evaluation.gates.read", "agent", agent)
    settings = request.app.state.settings
    limits = Thresholds(
        min_pass_rate=settings.gate_min_pass_rate
        if body.min_pass_rate is None
        else body.min_pass_rate,
        max_drop=settings.gate_max_drop if body.max_drop is None else body.max_drop,
    )
    thresholds = {"min_pass_rate": limits.min_pass_rate, "max_drop": limits.max_drop}
    async with _db(request).session(ctx) as s:
        t = await s.scalar(select(EvalSet).where(EvalSet.name == body.test_set))
        if t is None:
            return GateOut(
                passed=False,
                reasons=[{"code": "no_test_set", "test_set": body.test_set}],
                deltas={},
                test_set_id=None,
                run_id=None,
                baseline_run_id=None,
                scorecard=None,
                baseline_scorecard=None,
                thresholds=thresholds,
            )
        run = await _latest(s, agent, body.version, t.id, body.spec_hash)
        # Evaluated, but an earlier draft of this version: the content changed since.
        changed = run is None and await _latest(s, agent, body.version, t.id) is not None
        base = (
            await _latest(s, agent, body.baseline_version, t.id)
            if body.baseline_version and body.baseline_version != body.version
            else None
        )
        # A baseline on older cases is not comparable; the candidate must be on current ones.
        if base is not None and base.test_set_revision != t.revision:
            base = None
        stale = run is not None and run.test_set_revision != t.revision
        decision = gate(
            run.scorecard if run else None,
            base.scorecard if base else None,
            limits,
            stale=stale,
        )
        if changed:
            decision.reasons = [{"code": "changed_since_evaluation"}]
        return GateOut(
            passed=decision.passed,
            reasons=decision.reasons,
            deltas=decision.deltas,
            test_set_id=t.id,
            run_id=run.id if run else None,
            baseline_run_id=base.id if base else None,
            scorecard=run.scorecard if run else None,
            baseline_scorecard=base.scorecard if base else None,
            thresholds=thresholds,
        )
