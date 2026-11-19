"""Tenant deletion/export for governance itself: see ``Runner.own``. Retention runs and the outbox
go; deletion requests and their steps stay, as the certificate that the deletion happened."""

from nexiqon_governance.runner import Runner

__all__ = ["Runner"]
