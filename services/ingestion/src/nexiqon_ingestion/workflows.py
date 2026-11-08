"""Ingestion workflows (Temporal, IN-02). Durable: a killed worker resumes at the last activity.

* ``SyncSource``: discover -> per item (fetch -> scan -> process) -> finish (removes vanished docs)
* ``IngestDocument``: an uploaded file: scan -> process -> finish
* ``ReindexCollection``: reprocess every document (e.g. after an embedding-model change)
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from nexiqon_core.workflows import TenantScope
    from nexiqon_ingestion.wf_types import Discovery, FetchOutcome, ItemRef

PERMANENT = ["PermanentError"]
FETCH: dict[str, Any] = {
    "start_to_close_timeout": timedelta(minutes=5),
    "retry_policy": RetryPolicy(maximum_attempts=3, non_retryable_error_types=PERMANENT),
}
SCAN: dict[str, Any] = {
    "start_to_close_timeout": timedelta(minutes=5),
    "retry_policy": RetryPolicy(maximum_attempts=5, non_retryable_error_types=PERMANENT),
}
PROCESS: dict[str, Any] = {
    "start_to_close_timeout": timedelta(minutes=30),
    "retry_policy": RetryPolicy(
        initial_interval=timedelta(seconds=5),
        maximum_attempts=5,
        non_retryable_error_types=PERMANENT,
    ),
}
SHORT: dict[str, Any] = {
    "start_to_close_timeout": timedelta(minutes=2),
    "retry_policy": RetryPolicy(maximum_attempts=10),
}
DISCOVER: dict[str, Any] = {
    "start_to_close_timeout": timedelta(hours=1),
    "retry_policy": RetryPolicy(maximum_attempts=3, non_retryable_error_types=PERMANENT),
}


def _reason(exc: BaseException) -> tuple[str, str]:
    cause = exc.cause if isinstance(exc, ActivityError) else exc
    if isinstance(cause, ApplicationError):
        code = str(cause.details[0]) if cause.details else (cause.type or "failed")
        mapping = {
            "ScanUnavailable": "scan_unavailable",
            "FetchFailed": "fetch_failed",
            "Transient": "temporarily_unavailable",
        }
        return mapping.get(code, code), cause.message
    return "failed", str(cause or exc)


async def _document(scope: TenantScope, run_id: str, document_id: str, *, scan: bool) -> None:
    """scan -> process for one document; failures are recorded on the document, not raised."""
    try:
        if scan:
            clean = await workflow.execute_activity(
                "ingestion.scan", args=[scope, run_id, document_id], **SCAN
            )
            if not clean:
                return
        await workflow.execute_activity(
            "ingestion.process", args=[scope, run_id, document_id], **PROCESS
        )
    except ActivityError as exc:
        code, detail = _reason(exc)
        await workflow.execute_activity(
            "ingestion.mark_failed", args=[scope, run_id, document_id, code, detail], **SHORT
        )


async def _bounded(limit: int, jobs: list[Coroutine[Any, Any, None]]) -> None:
    for i in range(0, len(jobs), limit):
        await asyncio.gather(*jobs[i : i + limit])


@workflow.defn(name="ingestion.SyncSource")
class SyncSource:
    @workflow.run
    async def run(
        self, scope: TenantScope, run_id: str | None, source_id: str, concurrency: int = 4
    ) -> str:
        if run_id is None:  # started by a schedule
            run_id = await workflow.execute_activity(
                "ingestion.start_run", args=[scope, source_id], **SHORT
            )
        try:
            found: Discovery = await workflow.execute_activity(
                "ingestion.discover", args=[scope, run_id], result_type=Discovery, **DISCOVER
            )
        except ActivityError as exc:
            await workflow.execute_activity(
                "ingestion.finish_run", args=[scope, run_id, _reason(exc)[1]], **SHORT
            )
            return run_id

        async def one(item: ItemRef) -> None:
            try:
                outcome: FetchOutcome = await workflow.execute_activity(
                    "ingestion.fetch_item",
                    args=[scope, run_id, item],
                    result_type=FetchOutcome,
                    **FETCH,
                )
            except ActivityError as exc:
                workflow.logger.warning("fetch failed for %s: %s", item.uri, exc)
                return
            if outcome.changed and outcome.document_id:
                await _document(scope, run_id, outcome.document_id, scan=True)

        await _bounded(concurrency, [one(i) for i in found.items])
        failures = None
        await workflow.execute_activity(
            "ingestion.finish_run", args=[scope, run_id, failures], **SHORT
        )
        return run_id


@workflow.defn(name="ingestion.IngestDocument")
class IngestDocument:
    @workflow.run
    async def run(self, scope: TenantScope, run_id: str, document_id: str) -> str:
        await _document(scope, run_id, document_id, scan=True)
        await workflow.execute_activity("ingestion.finish_run", args=[scope, run_id, None], **SHORT)
        return run_id


@workflow.defn(name="ingestion.ReindexCollection")
class ReindexCollection:
    @workflow.run
    async def run(self, scope: TenantScope, run_id: str, concurrency: int = 4) -> str:
        ids: list[str] = await workflow.execute_activity(
            "ingestion.list_documents", args=[scope, run_id], result_type=list[str], **SHORT
        )
        await _bounded(concurrency, [_document(scope, run_id, i, scan=False) for i in ids])
        await workflow.execute_activity("ingestion.finish_run", args=[scope, run_id, None], **SHORT)
        return run_id


WORKFLOWS = [SyncSource, IngestDocument, ReindexCollection]
