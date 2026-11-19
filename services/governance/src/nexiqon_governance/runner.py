"""Activities for the lifecycle workflows (G-01, G-02). Each takes the tenant only from the
workflow's :class:`TenantScope`, and records every step, so Studio shows progress and a finished
deletion leaves its certificate."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from temporalio import activity
from temporalio.exceptions import ApplicationError

from nexiqon_core.blobs import BlobStore, tenant_key
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.events import add_event
from nexiqon_core.lifecycle import RetentionPolicy
from nexiqon_core.lifecycle_tables import TableLifecycle
from nexiqon_core.workflows import TenantScope
from nexiqon_governance.models import (
    KnownTenant,
    LifecycleRequest,
    LifecycleStep,
    Outbox,
    RetentionRun,
)
from nexiqon_governance.peers import SELF, Peers

log = structlog.get_logger(__name__)
SOURCE = "nexiqon/governance"


def _event(s: Any, scope: TenantScope, type_: str, subject: str, **data: Any) -> None:
    add_event(
        s,
        Outbox,
        scope.context(),
        source=SOURCE,
        type=f"nexiqon.governance.{type_}",
        subject=subject,
        data=data,
    )


@dataclass
class Runner:
    db: TenantSessionFactory
    peers: Peers
    blobs: BlobStore
    export_days: int = 7

    def activities(self) -> list[Any]:
        return [
            self.begin,
            self.step,
            self.finish,
            self.cancelled,
            self.retention_begin,
            self.retention_step,
            self.retention_finish,
            self.tenants,
        ]

    def own(self) -> TableLifecycle:
        """Governance's own tenant data. Deletion requests and their steps stay: they are the
        certificate that the tenant's data was removed (ids, counts and times only)."""
        return TableLifecycle(SELF, self.db, [RetentionRun, Outbox], export=[RetentionRun])

    # ------------------------------------------------------------------ deletion and export

    @activity.defn(name="governance.begin")
    async def begin(self, scope: TenantScope, request_id: str) -> list[str]:
        """Mark the request running and lay out one step per service. Returns the services in
        order; a request already done (a replay) returns no steps."""
        services = [*self.peers.services(), SELF]
        async with self.db.session(scope.context()) as s:
            req = await s.get(LifecycleRequest, uuid.UUID(request_id))
            if req is None:
                raise ApplicationError("request not found", non_retryable=True)
            if req.status in ("completed", "cancelled"):
                return []
            req.status = "running"
            for i, service in enumerate(services):
                await s.execute(
                    insert(LifecycleStep)
                    .values(
                        id=uuid.uuid4(),
                        tenant_id=req.tenant_id,
                        request_id=req.id,
                        service=service,
                        position=i,
                        status="pending",
                        attempts=0,
                        detail={},
                    )
                    .on_conflict_do_nothing(index_elements=["request_id", "service"])
                )
            done = set(
                await s.scalars(
                    select(LifecycleStep.service).where(
                        LifecycleStep.request_id == req.id, LifecycleStep.status == "done"
                    )
                )
            )
            return [svc for svc in services if svc not in done]

    async def _record(
        self, scope: TenantScope, request_id: str, service: str, **values: Any
    ) -> None:
        async with self.db.session(scope.context()) as s:
            await s.execute(
                update(LifecycleStep)
                .where(
                    LifecycleStep.request_id == uuid.UUID(request_id),
                    LifecycleStep.service == service,
                )
                .values(**values)
            )

    @activity.defn(name="governance.step")
    async def step(self, scope: TenantScope, request_id: str, kind: str, service: str) -> bool:
        """One service's part. Deletion must confirm that nothing is left (else it is retried and
        then fails the request); export stores the service's manifest for the archive."""
        tenant = uuid.UUID(scope.tenant_id)
        attempt = activity.info().attempt
        await self._record(scope, request_id, service, status="running", attempts=attempt)
        try:
            if service == SELF:
                own = self.own()
                result: dict[str, Any] = (
                    (await own.delete_tenant(tenant)).model_dump(mode="json")
                    if kind == "delete"
                    else (await own.export_tenant(tenant)).model_dump(mode="json")
                )
            else:
                result = await self.peers.lifecycle(service, tenant, kind)
        except Exception as exc:
            await self._record(
                scope, request_id, service, status="failed", detail={"error": str(exc)[:500]}
            )
            raise
        if kind == "delete":
            detail = {
                "deleted": result.get("deleted") or {},
                "residue_check_passed": bool(result.get("residue_check_passed")),
            }
            if not detail["residue_check_passed"]:
                await self._record(scope, request_id, service, status="failed", detail=detail)
                raise ApplicationError(f"{service} still holds data for the tenant")
        else:
            artifacts = result.get("artifacts") or []
            await self.blobs.put(
                tenant_key(tenant, "exports", request_id, f"{service}.json"),
                json.dumps(result, ensure_ascii=False).encode(),
                "application/json",
            )
            detail = {
                "artifacts": len(artifacts),
                "rows": sum(int(a.get("rows") or 0) for a in artifacts),
            }
        await self._record(
            scope, request_id, service, status="done", detail=detail, finished_at=datetime.now(UTC)
        )
        return True

    @activity.defn(name="governance.finish")
    async def finish(
        self, scope: TenantScope, request_id: str, kind: str, services: list[str], error: str | None
    ) -> None:
        tenant = uuid.UUID(scope.tenant_id)
        key = None
        if kind == "export" and error is None:
            key = await self._archive(tenant, request_id, services)
        async with self.db.session(scope.context()) as s:
            req = await s.get(LifecycleRequest, uuid.UUID(request_id))
            if req is None:
                return
            req.status = "failed" if error else "completed"
            req.error = error[:1000] if error else None
            req.finished_at = datetime.now(UTC)
            req.result_key = key
            _event(
                s,
                scope,
                f"tenant.{kind}.{req.status}",
                f"request/{request_id}",
                request_id=request_id,
            )
        if kind == "delete" and error is None:
            async with self.db.system_session() as s:
                await s.execute(
                    update(KnownTenant)
                    .where(KnownTenant.tenant_id == tenant)
                    .values(deleted_at=datetime.now(UTC))
                )

    async def _archive(self, tenant: uuid.UUID, request_id: str, services: list[str]) -> str:
        buffer = io.BytesIO()
        summary: dict[str, Any] = {
            "tenant_id": str(tenant),
            "request_id": request_id,
            "services": {},
        }
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for service in services:
                part = tenant_key(tenant, "exports", request_id, f"{service}.json")
                data = await self.blobs.get(part)
                z.writestr(f"{service}.json", data)
                manifest = json.loads(data)
                summary["services"][service] = [
                    {"kind": a.get("kind"), "rows": a.get("rows")}
                    for a in manifest.get("artifacts") or []
                ]
                await self.blobs.delete(part)
            summary["created_at"] = datetime.now(UTC).isoformat()
            summary["expires_at"] = (
                datetime.now(UTC) + timedelta(days=self.export_days)
            ).isoformat()
            z.writestr("manifest.json", json.dumps(summary, indent=2))
        key = tenant_key(tenant, "exports", f"{request_id}.zip")
        await self.blobs.put(key, buffer.getvalue(), "application/zip")
        return key

    @activity.defn(name="governance.cancelled")
    async def cancelled(self, scope: TenantScope, request_id: str) -> None:
        async with self.db.session(scope.context()) as s:
            req = await s.get(LifecycleRequest, uuid.UUID(request_id))
            if req is not None and req.status == "scheduled":
                req.status, req.finished_at = "cancelled", datetime.now(UTC)
                _event(
                    s,
                    scope,
                    "tenant.delete.cancelled",
                    f"request/{request_id}",
                    request_id=request_id,
                )

    # ------------------------------------------------------------------ retention (G-01)

    @activity.defn(name="governance.retention_begin")
    async def retention_begin(self, scope: TenantScope, run_id: str | None) -> list[str]:
        """Create the run (scheduled sweeps pass none) and return its id and the services."""
        tenant = uuid.UUID(scope.tenant_id)
        policy = await self.peers.policy(tenant)
        async with self.db.session(scope.context()) as s:
            if run_id is None:
                run = RetentionRun(
                    tenant_id=tenant,
                    started_by=scope.actor_id,
                    status="running",
                    policy=policy.model_dump(),
                    purged={},
                    errors={},
                )
                s.add(run)
                await s.flush()
                run_id = str(run.id)
            else:
                existing = await s.get(RetentionRun, uuid.UUID(run_id))
                if existing is not None:
                    existing.policy = policy.model_dump()
        return [run_id, *self.peers.services(), SELF]

    @activity.defn(name="governance.retention_step")
    async def retention_step(self, scope: TenantScope, run_id: str, service: str) -> dict[str, Any]:
        tenant = uuid.UUID(scope.tenant_id)
        async with self.db.session(scope.context()) as s:
            run = await s.get(RetentionRun, uuid.UUID(run_id))
            policy_dict = dict(run.policy) if run else {}
        policy = RetentionPolicy.model_validate(policy_dict)
        try:
            if service == SELF:
                purged = await self._purge_own(tenant)
            else:
                purged = await self.peers.retention(service, tenant, policy)
        except Exception as exc:  # one service down never stops the sweep
            return {"service": service, "error": str(exc)[:300]}
        return {"service": service, "purged": purged}

    async def _purge_own(self, tenant: uuid.UUID) -> dict[str, int]:
        """Export archives older than their link lifetime."""
        cutoff = datetime.now(UTC) - timedelta(days=self.export_days)
        removed = 0
        async with self.db.scoped({"tenant_id": str(tenant)}) as s:
            old = list(
                await s.scalars(
                    select(LifecycleRequest).where(
                        LifecycleRequest.kind == "export",
                        LifecycleRequest.result_key.is_not(None),
                        LifecycleRequest.finished_at < cutoff,
                    )
                )
            )
            for req in old:
                try:
                    await self.blobs.delete(str(req.result_key))
                except Exception as exc:
                    log.warning("export_cleanup_failed", error=str(exc))
                    continue
                req.result_key = None
                removed += 1
        return {"export_archives": removed}

    @activity.defn(name="governance.retention_finish")
    async def retention_finish(
        self, scope: TenantScope, run_id: str, results: list[dict[str, Any]]
    ) -> None:
        purged = {r["service"]: r["purged"] for r in results if "purged" in r}
        errors = {r["service"]: r["error"] for r in results if "error" in r}
        async with self.db.session(scope.context()) as s:
            run = await s.get(RetentionRun, uuid.UUID(run_id))
            if run is None:
                return
            run.purged, run.errors = purged, errors
            run.status = "failed" if errors and not purged else "completed"
            run.finished_at = datetime.now(UTC)
            totals = {
                f"{svc}.{k}": n for svc, kinds in purged.items() for k, n in kinds.items() if n
            }
            _event(
                s,
                scope,
                "retention.completed",
                f"retention/{run_id}",
                run_id=run_id,
                purged=totals,
                errors=sorted(errors),
            )

    @activity.defn(name="governance.tenants")
    async def tenants(self) -> list[str]:
        async with self.db.system_session() as s:
            rows = await s.scalars(
                select(KnownTenant.tenant_id).where(KnownTenant.deleted_at.is_(None))
            )
            return [str(t) for t in rows]


async def remember_tenant(db: TenantSessionFactory, tenant: uuid.UUID) -> None:
    async with db.system_session() as s:
        await s.execute(
            insert(KnownTenant)
            .values(tenant_id=tenant, created_at=datetime.now(UTC))
            .on_conflict_do_nothing(index_elements=["tenant_id"])
        )


class TenantRegistry:
    """Consumer of identity's tenant events: the platform-wide sweep's list of tenants."""

    def __init__(self, db: TenantSessionFactory) -> None:
        self.db = db

    async def __call__(self, event: dict[str, Any]) -> None:
        if str(event.get("type", "")).endswith("tenant.created"):
            await remember_tenant(self.db, uuid.UUID(str(event["nexiqontenantid"])))
