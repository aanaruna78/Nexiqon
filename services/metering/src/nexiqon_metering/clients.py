"""Calls metering makes as itself: config (an assistant's pack, for its KPIs) and conversation
(unanswered questions, for content gaps)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from nexiqon_core.errors import ServiceUnavailable
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.tenancy import CONTEXT_HEADER


class Peers:
    def __init__(
        self,
        tokens: ServiceTokens,
        config_url: str | None,
        conversation_url: str | None,
        environment: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.tokens = tokens
        self.config = config_url.rstrip("/") if config_url else None
        self.conversation = conversation_url.rstrip("/") if conversation_url else None
        self.environment = environment
        self.client = httpx.AsyncClient(transport=transport, timeout=30.0, trust_env=False)

    async def _get(self, base: str | None, tenant: uuid.UUID, path: str, **params: Any) -> Any:
        if base is None:
            raise ServiceUnavailable(f"No URL for {path}")
        try:
            r = await self.client.get(
                f"{base}{path}",
                params={k: v for k, v in params.items() if v is not None},
                headers={CONTEXT_HEADER: self.tokens.for_tenant(tenant)},
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(str(exc)) from exc
        if r.status_code == 404:
            return None
        if r.status_code >= 300:
            raise ServiceUnavailable(f"{path} answered {r.status_code}")
        return r.json()

    async def kpis(self, tenant: uuid.UUID, agent: str) -> list[dict[str, Any]]:
        resolved = await self._get(
            self.config, tenant, f"/v1/resolve/agents/{agent}", environment=self.environment
        )
        pack = (resolved or {}).get("pack") or {}
        return list((pack.get("analytics") or {}).get("kpis") or [])

    async def gap_questions(
        self, tenant: uuid.UUID, agent: str | None, days: int
    ) -> list[dict[str, Any]]:
        found = await self._get(
            self.conversation, tenant, "/v1/insights/gap-questions", agent=agent, days=days
        )
        return list(found or [])

    async def aclose(self) -> None:
        await self.client.aclose()
