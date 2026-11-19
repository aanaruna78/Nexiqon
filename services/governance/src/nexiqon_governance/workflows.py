"""Tenant lifecycle workflows (Temporal, G-01, G-02). Durable: a killed worker resumes at the
next service; steps already done are not repeated."""

from __future__ import annotations

import contextlib
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
STEP: dict[str, Any] = {
    "start_to_close_timeout": timedelta(minutes=30),
    "retry_policy": RetryPolicy(
        initial_interval=timedelta(seconds=5),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=5),
        maximum_attempts=5,
    ),
}


@workflow.defn(name="governance.TenantRequest")
class TenantRequest:
    """``kind`` is delete (after ``grace_seconds``, cancellable) or export."""

    def __init__(self) -> None:
        self._cancel = False

    @workflow.signal
    def cancel(self) -> None:
        self._cancel = True

    @workflow.run
    async def run(
        self, scope: TenantScope, request_id: str, kind: str, grace_seconds: float
    ) -> str:
        if kind == "delete" and grace_seconds > 0:
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self._cancel, timeout=timedelta(seconds=grace_seconds)
                )
            if self._cancel:
                await workflow.execute_activity(
                    "governance.cancelled", args=[scope, request_id], **SHORT
                )
                return "cancelled"
        services: list[str] = await workflow.execute_activity(
            "governance.begin", args=[scope, request_id], result_type=list[str], **SHORT
        )
        if not services:
            return "already done"
        error = None
        for service in services:  # in order: identity (the organization) goes last
            try:
                await workflow.execute_activity(
                    "governance.step", args=[scope, request_id, kind, service], **STEP
                )
            except ActivityError as exc:
                error = f"{service}: {exc.cause or exc}"
                break
        await workflow.execute_activity(
            "governance.finish", args=[scope, request_id, kind, services, error], **SHORT
        )
        return "failed" if error else "completed"


@workflow.defn(name="governance.RetentionSweep")
class RetentionSweep:
    @workflow.run
    async def run(self, scope: TenantScope, run_id: str | None) -> str:
        found: list[str] = await workflow.execute_activity(
            "governance.retention_begin", args=[scope, run_id], result_type=list[str], **SHORT
        )
        run, services = found[0], found[1:]
        results: list[dict[str, Any]] = []
        for service in services:
            results.append(
                await workflow.execute_activity(
                    "governance.retention_step",
                    args=[scope, run, service],
                    result_type=dict[str, Any],
                    **SHORT,
                )
            )
        await workflow.execute_activity(
            "governance.retention_finish", args=[scope, run, results], **SHORT
        )
        return run


@workflow.defn(name="governance.RetentionAll")
class RetentionAll:
    """The daily platform-wide sweep: one child sweep per tenant (a schedule starts it)."""

    @workflow.run
    async def run(self) -> int:
        tenants: list[str] = await workflow.execute_activity(
            "governance.tenants", result_type=list[str], **SHORT
        )
        for tenant in tenants:
            scope = TenantScope(tenant_id=tenant, actor_id="retention-schedule")
            try:
                await workflow.execute_child_workflow(
                    "governance.RetentionSweep",
                    args=[scope, None],
                    id=f"{tenant}:retention:{workflow.info().workflow_id}",
                )
            except Exception as exc:  # one tenant's failure never stops the others
                workflow.logger.warning("retention failed for %s: %s", tenant, exc)
        return len(tenants)


WORKFLOWS = [TenantRequest, RetentionSweep, RetentionAll]
