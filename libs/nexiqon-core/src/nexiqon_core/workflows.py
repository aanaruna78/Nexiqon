"""Tenant-scoped Temporal workflows (EV-02, ADR 0007).

Every workflow input carries a :class:`TenantScope`. Activities derive their tenant context *only*
from that scope, so RLS confines all data access to that tenant; workflow ids are tenant-prefixed
so tenants cannot collide or signal each other's workflows.

    @activity.defn
    async def export_documents(scope: TenantScope, ...) -> ...:
        async with sessions.session(scope.context()) as s: ...
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor

from nexiqon_core.errors import BadRequest
from nexiqon_core.settings import WorkflowSettings
from nexiqon_core.tenancy import TenantContext

_KEY = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


@dataclass(frozen=True)
class TenantScope:
    tenant_id: str
    actor_id: str

    @classmethod
    def of(cls, ctx: TenantContext) -> TenantScope:
        return cls(tenant_id=str(ctx.tenant_id), actor_id=ctx.actor_id)

    def context(self) -> TenantContext:
        try:
            tenant = uuid.UUID(self.tenant_id)
        except ValueError as exc:
            raise BadRequest("Invalid tenant scope") from exc
        return TenantContext(
            tenant_id=tenant, actor_id=f"workflow:{self.actor_id}", actor_type="service"
        )


def workflow_id(scope: TenantScope, name: str, key: str) -> str:
    if not (_KEY.match(name) and _KEY.match(key)):
        raise BadRequest("Invalid workflow name or key")
    return f"{scope.tenant_id}:{name}:{key}"


async def connect(settings: WorkflowSettings) -> Client:
    """Temporal client with trace propagation into workflows and activities."""
    return await Client.connect(
        settings.address, namespace=settings.namespace, interceptors=[TracingInterceptor()]
    )
