"""Tenant-scoped service tokens for background work (ADR 0017).

A workflow acting for a tenant (e.g. ingestion calling the model gateway) has no user token. The
service signs a short-lived context token with its own key; verifiers accept that key only for
``actor = role = "service:<name>"`` (``ContextTokenSettings.service_keys``), and OPA grants that
role a narrow permission list. Tokens are cached per tenant until shortly before expiry.
"""

from __future__ import annotations

import time
import uuid

from nexiqon_core.errors import ServiceUnavailable
from nexiqon_core.settings import ContextTokenSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import ContextTokenIssuer, TenantContext

REFRESH_MARGIN_SECONDS = 60


class ServiceTokens:
    def __init__(
        self, service: str, tokens: ContextTokenSettings, identity: ServiceIdentitySettings
    ) -> None:
        self.service = service
        self.identity = f"service:{service}"
        self._ttl = identity.ttl_seconds
        self._issuer = (
            ContextTokenIssuer(
                identity.private_key.get_secret_value(),
                identity.key_id,
                tokens,
                identity.ttl_seconds,
            )
            if identity.key_id and identity.private_key
            else None
        )
        self._cache: dict[uuid.UUID, tuple[float, str]] = {}

    @property
    def configured(self) -> bool:
        return self._issuer is not None

    def context(self, tenant_id: uuid.UUID) -> TenantContext:
        return TenantContext(
            tenant_id=tenant_id,
            actor_id=self.identity,
            actor_type="service",
            roles=frozenset({self.identity}),
        )

    def for_tenant(self, tenant_id: uuid.UUID) -> str:
        if self._issuer is None:
            raise ServiceUnavailable(f"Service identity for {self.service} is not configured")
        now = time.time()
        hit = self._cache.get(tenant_id)
        if hit is not None and hit[0] > now + REFRESH_MARGIN_SECONDS:
            return hit[1]
        token = self._issuer.issue(self.context(tenant_id), now=now)
        self._cache[tenant_id] = (now + self._ttl, token)
        return token
