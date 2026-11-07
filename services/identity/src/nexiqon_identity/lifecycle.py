"""Tenant deletion/export hooks for identity.

TODO: replace NoTenantData when this service starts storing tenant data. Deletion must remove
everything the service holds for the tenant and verify no residue remains (ARCHITECTURE §3).
"""

from nexiqon_core.lifecycle import NoTenantData, TenantLifecycle


def lifecycle(service: str) -> TenantLifecycle:
    return NoTenantData(service)
