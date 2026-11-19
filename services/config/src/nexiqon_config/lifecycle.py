"""Tenant deletion/export for config: every object, version, deployment and its history."""

from __future__ import annotations

from nexiqon_config.models import (
    ConfigDeployment,
    ConfigObject,
    ConfigVersion,
    DeploymentHistory,
    Outbox,
)
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.lifecycle import NoTenantData, TenantLifecycle
from nexiqon_core.lifecycle_tables import TableLifecycle


def lifecycle(service: str, db: TenantSessionFactory | None = None) -> TenantLifecycle:
    if db is None:
        return NoTenantData(service)
    return TableLifecycle(
        service,
        db,
        [DeploymentHistory, ConfigDeployment, ConfigVersion, ConfigObject, Outbox],
        export=[ConfigObject, ConfigVersion, ConfigDeployment, DeploymentHistory],
    )
