"""Feature flags through OpenFeature (CF-06). Evaluated per tenant; provider is configuration.

    flags = Flags(settings.flags, service="config")
    if flags.enabled("studio-answer-inspector", ctx): ...

Providers: flagd (deployments; flag definitions in deploy/compose/flags/flags.json), in-memory
(tests), none (every flag returns its default).
"""

from __future__ import annotations

from typing import Any

from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from openfeature.provider.in_memory_provider import InMemoryFlag, InMemoryProvider

from nexiqon_core.settings import FlagSettings
from nexiqon_core.tenancy import TenantContext


def evaluation_context(ctx: TenantContext | None) -> EvaluationContext:
    if ctx is None:
        return EvaluationContext()
    return EvaluationContext(
        targeting_key=str(ctx.tenant_id),
        attributes={
            "tenant_id": str(ctx.tenant_id),
            "region": ctx.region or "default",
            "actor_type": ctx.actor_type,
            "roles": sorted(ctx.roles),
        },
    )


class Flags:
    def __init__(
        self,
        settings: FlagSettings,
        service: str,
        in_memory: dict[str, InMemoryFlag[Any]] | None = None,
    ) -> None:
        if settings.provider == "flagd":
            from nexiqon_core.adapters.flagd import flagd_provider

            api.set_provider(
                flagd_provider(settings.flagd_host, settings.flagd_port), domain=service
            )
        elif settings.provider == "in_memory":
            api.set_provider(InMemoryProvider(in_memory or {}), domain=service)
        self._client = api.get_client(domain=service)
        self._remote = settings.provider == "flagd"

    async def ready(self) -> bool:
        """Remote providers connect in the background; until then flags return their defaults."""
        from openfeature.provider import ProviderStatus

        return not self._remote or self._client.get_provider_status() == ProviderStatus.READY

    def enabled(self, key: str, ctx: TenantContext | None, default: bool = False) -> bool:
        return bool(self._client.get_boolean_value(key, default, evaluation_context(ctx)))

    def string(self, key: str, ctx: TenantContext | None, default: str) -> str:
        return str(self._client.get_string_value(key, default, evaluation_context(ctx)))
