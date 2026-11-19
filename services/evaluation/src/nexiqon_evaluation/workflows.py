"""Evaluation workflow (Temporal, QA-01). A killed worker resumes at the next unscored case."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from nexiqon_core.workflows import TenantScope

SHORT: dict[str, Any] = {
    "start_to_close_timeout": timedelta(minutes=2),
    "retry_policy": RetryPolicy(maximum_attempts=10),
}


def case_options(timeout_seconds: int) -> dict[str, Any]:
    return {
        "start_to_close_timeout": timedelta(seconds=timeout_seconds + 30),
        "retry_policy": RetryPolicy(initial_interval=timedelta(seconds=2), maximum_attempts=3),
    }


@workflow.defn(name="evaluation.RunEvaluation")
class RunEvaluation:
    @workflow.run
    async def run(
        self, scope: TenantScope, run_id: str, concurrency: int = 4, case_timeout: int = 120
    ) -> str:
        try:
            ids: list[str] = await workflow.execute_activity(
                "evaluation.start", args=[scope, run_id], result_type=list[str], **SHORT
            )
            options = case_options(case_timeout)

            async def one(case_id: str) -> None:
                try:
                    await workflow.execute_activity(
                        "evaluation.run_case", args=[scope, run_id, case_id], **options
                    )
                except ActivityError as exc:  # a broken case never stops the run
                    workflow.logger.warning("case %s failed: %s", case_id, exc)

            for i in range(0, len(ids), concurrency):
                await asyncio.gather(*(one(c) for c in ids[i : i + concurrency]))
        except ActivityError as exc:
            await workflow.execute_activity(
                "evaluation.finish", args=[scope, run_id, str(exc.cause or exc)], **SHORT
            )
            return run_id
        await workflow.execute_activity("evaluation.finish", args=[scope, run_id, None], **SHORT)
        return run_id


WORKFLOWS = [RunEvaluation]
