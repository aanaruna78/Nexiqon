"""Tenant deletion/export for audit. The log is append-only, except during a tenant deletion
(``app.tenant_deletion``), when the whole chain for that tenant goes. The deletion itself is
recorded by governance (a certificate with no personal data)."""

from __future__ import annotations

from nexiqon_audit.models import AuditEvent
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import NoTenantData, TenantLifecycle
from nexiqon_core.lifecycle_tables import TableLifecycle


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    if db is None:
        return NoTenantData(service)
    return TableLifecycle(service, db, [AuditEvent], export=[AuditEvent])
