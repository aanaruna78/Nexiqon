"""Governance's calls to every service's lifecycle endpoints, as itself (``service:governance``)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from nexiqon_core.directory import Topology
from nexiqon_core.errors import ServiceUnavailable
from nexiqon_core.lifecycle import RetentionPolicy
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.tenancy import CONTEXT_HEADER
from nexiqon_governance.settings import ServiceSettings

SELF = "governance"
# Removed last, in this order: identity holds the organization itself.
LAST = ("config", "identity")


def service_order(names: list[str]) -> list[str]:
    """Every service but governance, the ones others depend on last."""
    rest = sorted(n for n in names if n != SELF and n not in LAST)
    return rest + [n for n in LAST if n in names]


class Peers:
    def __init__(
        self,
        settings: ServiceSettings,
        tokens: ServiceTokens,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.tokens = tokens
        self.client = httpx.AsyncClient(transport=transport, timeout=300.0, trust_env=False)

    def services(self) -> list[str]:
        if self.settings.service_urls:
            return service_order(list(self.settings.service_urls))
        topology = Topology.load(self.settings.groups_file)
        return service_order([s for g in topology.groups.values() for s in g.services])

    def url(self, service: str) -> str:
        explicit = self.settings.service_urls.get(service)
        if explicit:
            return explicit.rstrip("/")
        return Topology.load(self.settings.groups_file).url_for(service)

    async def _post(self, service: str, tenant: uuid.UUID, path: str, body: Any = None) -> Any:
        try:
            r = await self.client.post(
                f"{self.url(service)}{path}",
                headers={CONTEXT_HEADER: self.tokens.for_tenant(tenant)},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(f"{service}: {exc}") from exc
        if r.status_code >= 300:
            raise ServiceUnavailable(f"{service} answered {r.status_code}: {r.text[:300]}")
        return r.json()

    async def lifecycle(self, service: str, tenant: uuid.UUID, op: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._post(service, tenant, f"/v1/_lifecycle/{op}")
        return result

    async def retention(
        self, service: str, tenant: uuid.UUID, policy: RetentionPolicy
    ) -> dict[str, int]:
        result = await self._post(service, tenant, "/v1/_lifecycle/retention", policy.model_dump())
        return dict(result.get("purged") or {})

    async def policy(self, tenant: uuid.UUID) -> RetentionPolicy:
        """The tenant's own retention profile (from config), or the platform default."""
        name = self.settings.retention_profile
        try:
            r = await self.client.get(
                f"{self.url('config')}/v1/resolve/profiles/retention_profile/{name}",
                params={"environment": self.settings.profile_environment},
                headers={CONTEXT_HEADER: self.tokens.for_tenant(tenant)},
            )
        except (httpx.HTTPError, KeyError, OSError):
            return self.settings.fallback_retention
        if r.status_code != 200:
            return self.settings.fallback_retention
        spec = r.json().get("profile") or {}
        return RetentionPolicy.model_validate(
            {k: v for k, v in spec.items() if k in RetentionPolicy.model_fields}
        )

    async def aclose(self) -> None:
        await self.client.aclose()
