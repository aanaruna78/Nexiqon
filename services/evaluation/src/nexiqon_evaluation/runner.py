"""Evaluation runs (QA-01): ask the assistant every case of a test set, score each answer with the
evaluator plugins, then write the run's scorecard. Activities take the tenant only from the
workflow's :class:`TenantScope`, so RLS confines them to that tenant (ADR 0007)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from temporalio import activity
from temporalio.exceptions import ApplicationError

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import ServiceUnavailable
from nexiqon_core.events import add_event
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.workflows import TenantScope
from nexiqon_evaluation.clients import AgentRuntime, Config
from nexiqon_evaluation.models import EvalResult, EvalRun, EvalSet, EvalSetCase, Outbox
from nexiqon_evaluation.scoring import CaseOutcome, scorecard
from nexiqon_sdk import EvalCase, EvalObservation, PluginKind, Registry

log = structlog.get_logger(__name__)
SOURCE = "nexiqon/evaluation"


def case_of(row: EvalSetCase) -> EvalCase:
    return EvalCase(
        question=row.question,
        lang=row.lang,
        expected_source=row.expected_source,
        expected_section=row.expected_section,
        expected_phrases=tuple(row.expected_phrases or ()),
        must_abstain=row.must_abstain,
    )


async def score_case(
    registry: Registry, names: list[str], case: EvalCase, seen: EvalObservation
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Every applicable evaluator scores the case; it passes when all of them pass."""
    scores: dict[str, dict[str, Any]] = {}
    for manifest in registry.manifests(PluginKind.EVALUATOR):
        if names and manifest.name not in names:
            continue
        plugin = registry.get(PluginKind.EVALUATOR, manifest.name)
        if not plugin.applies(case):
            continue
        s = await plugin.score(case, seen, {})
        scores[manifest.name] = {"value": s.value, "passed": s.passed, "detail": s.detail}
    passed = bool(scores) and all(s["passed"] for s in scores.values()) and not seen.error
    return scores, passed


@dataclass
class Runner:
    db: TenantSessionFactory
    tokens: ServiceTokens
    agents: AgentRuntime
    registry: Registry
    config: Config

    def activities(self) -> list[Any]:
        return [self.start, self.run_case, self.finish]

    @activity.defn(name="evaluation.start")
    async def start(self, scope: TenantScope, run_id: str) -> list[str]:
        async with self.db.session(scope.context()) as s:
            run = await s.get(EvalRun, uuid.UUID(run_id))
            if run is None:
                raise ApplicationError("run not found", non_retryable=True)
            ids = list(
                await s.scalars(
                    select(EvalSetCase.id)
                    .where(EvalSetCase.test_set_id == run.test_set_id)
                    .order_by(EvalSetCase.created_at, EvalSetCase.id)
                )
            )
            run.status, run.case_count = "running", len(ids)
            return [str(i) for i in ids]

    @activity.defn(name="evaluation.run_case")
    async def run_case(self, scope: TenantScope, run_id: str, case_id: str) -> bool:
        ctx = scope.context()
        async with self.db.session(ctx) as s:
            run = await s.get(EvalRun, uuid.UUID(run_id))
            row = await s.get(EvalSetCase, uuid.UUID(case_id))
            if run is None or row is None:  # case deleted while running: nothing to score
                return False
            test_set = await s.get(EvalSet, run.test_set_id)
            names = list(test_set.evaluators or []) if test_set else []
            agent, version, case = run.agent, run.version, case_of(row)
        token = self.tokens.for_tenant(ctx.tenant_id)
        try:
            seen, agent_run = await self.agents.ask(
                token, agent, version, f"eval-{run_id}-{case_id}", case.question, case.lang
            )
        except ServiceUnavailable as exc:  # retried by Temporal; the case fails after the last try
            info = activity.info()
            if info.attempt < 3:
                raise
            seen, agent_run = EvalObservation(answer="", abstained=True, error=str(exc)), None
        scores, passed = await score_case(self.registry, names, case, seen)
        values = {
            "id": uuid.uuid4(),
            "tenant_id": ctx.tenant_id,
            "run_id": uuid.UUID(run_id),
            "case_id": uuid.UUID(case_id),
            "question": case.question,
            "lang": case.lang,
            "answer": seen.answer,
            "abstained": seen.abstained,
            "kind": seen.kind,
            "citations": [
                {"citation": c.citation, "source_uri": c.source_uri} for c in seen.citations
            ],
            "scores": scores,
            "passed": passed,
            "latency_ms": seen.latency_ms,
            "tokens": seen.tokens,
            "cost": seen.cost,
            "agent_run_id": agent_run,
            "error": (seen.error or None) and str(seen.error)[:1000],
        }
        async with self.db.session(ctx) as s:
            stmt = insert(EvalResult).values(**values)
            update = {k: stmt.excluded[k] for k in values if k not in ("id", "tenant_id")}
            await s.execute(
                stmt.on_conflict_do_update(index_elements=["run_id", "case_id"], set_=update)
            )
            done = await s.scalar(
                select(func.count())
                .select_from(EvalResult)
                .where(EvalResult.run_id == uuid.UUID(run_id))
            )
            run = await s.get(EvalRun, uuid.UUID(run_id))
            if run is not None:
                run.done_count = int(done or 0)
        return passed

    @activity.defn(name="evaluation.finish")
    async def finish(self, scope: TenantScope, run_id: str, error: str | None) -> None:
        ctx = scope.context()
        if error is None:  # was the draft edited while it was being evaluated?
            async with self.db.session(ctx) as s:
                started = await s.get(EvalRun, uuid.UUID(run_id))
            if started is not None:
                now = await self.config.spec_hash(
                    self.tokens.for_tenant(ctx.tenant_id), started.agent, started.version
                )
                if now != started.spec_hash:
                    error = "changed_during_run"
        async with self.db.session(ctx) as s:
            run = await s.get(EvalRun, uuid.UUID(run_id))
            if run is None:
                return
            rows = list(await s.scalars(select(EvalResult).where(EvalResult.run_id == run.id)))
            card = scorecard(
                [
                    CaseOutcome(
                        lang=r.lang,
                        passed=r.passed,
                        scores=r.scores,
                        latency_ms=r.latency_ms,
                        tokens=r.tokens,
                        cost=r.cost,
                        error=bool(r.error),
                    )
                    for r in rows
                ]
                # Cases that never produced a result (a bug, not an answer) count as failures.
                + [
                    CaseOutcome(lang="unknown", passed=False, scores={}, error=True)
                    for _ in range(max(0, run.case_count - len(rows)))
                ]
            )
            run.scorecard = card
            run.status = "failed" if error else "completed"
            run.error = error[:1000] if error else None
            run.finished_at = datetime.now(UTC)
            add_event(
                s,
                Outbox,
                ctx,
                source=SOURCE,
                type=f"nexiqon.evaluation.run.{run.status}",
                subject=f"agent/{run.agent}",
                data={
                    "run_id": run_id,
                    "agent": run.agent,
                    "version": run.version,
                    "test_set_id": str(run.test_set_id),
                    "pass_rate": card["pass_rate"],
                    "cases": card["cases"],
                },
            )
