"""Tool definitions and agent allowlists from config, read with tool-gateway's own identity."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from nexiqon_core.errors import NotFound, ServiceUnavailable
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.tenancy import CONTEXT_HEADER

RISK_ORDER = ("read", "write", "high")


@dataclass(frozen=True)
class ToolDef:
    name: str
    version: int
    spec: dict[str, Any]

    @property
    def risk(self) -> str:
        return str(self.spec.get("risk_level", "high"))

    @property
    def needs_confirmation(self) -> bool:
        """Writes always need the caller's confirmation (security floor); reads only if asked."""
        return self.risk != "read" or self.spec.get("confirmation") == "always"

    @property
    def result_classification(self) -> str:
        return str(self.spec.get("result_classification") or "confidential")

    def public(self) -> dict[str, Any]:
        """What callers (and models) may see: no URLs, hosts, headers or credential names."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.spec.get("description", ""),
            "kind": self.spec.get("kind"),
            "risk_level": self.risk,
            "needs_confirmation": self.needs_confirmation,
            "input_schema": self.spec.get("input_schema") or {"type": "object", "properties": {}},
            "result_classification": self.result_classification,
        }


class Registry:
    def __init__(
        self,
        base_url: str | None,
        tokens: ServiceTokens,
        environment: str,
        cache_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/") if base_url else None
        self._tokens = tokens
        self._env = environment
        self._ttl = cache_seconds
        self._client = httpx.AsyncClient(transport=transport, timeout=5.0, trust_env=False)
        self._cache: dict[tuple[uuid.UUID, str, str], tuple[float, Any]] = {}

    async def _get(self, tenant: uuid.UUID, path: str, key: tuple[str, str]) -> dict[str, Any]:
        cache_key = (tenant, *key)
        hit = self._cache.get(cache_key)
        if hit and hit[0] > time.monotonic():
            result: dict[str, Any] = hit[1]
            return result
        if self._base is None:
            raise ServiceUnavailable("Config service URL is not configured")
        try:
            r = await self._client.get(
                f"{self._base}{path}",
                params={"environment": self._env},
                headers={CONTEXT_HEADER: self._tokens.for_tenant(tenant)},
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Config service unreachable") from exc
        if r.status_code == 404:
            raise NotFound(r.json().get("detail", "not found"))
        if r.status_code >= 400:
            raise ServiceUnavailable(f"Config service returned {r.status_code}")
        body: dict[str, Any] = r.json()
        if self._ttl > 0:
            self._cache[cache_key] = (time.monotonic() + self._ttl, body)
        return body

    async def tool(self, tenant: uuid.UUID, name: str) -> ToolDef:
        body = await self._get(tenant, f"/v1/resolve/objects/tool/{name}", ("tool", name))
        return ToolDef(name=name, version=int(body["version"]), spec=dict(body["spec"]))

    async def agent_tools(self, tenant: uuid.UUID, agent: str) -> tuple[set[str], dict[str, str]]:
        """Tools the agent may use, and the pack's risk levels for them (the stricter one wins)."""
        body = await self._get(tenant, f"/v1/resolve/agents/{agent}", ("agent", agent))
        allowed = set((body.get("config") or {}).get("tools") or [])
        risks = {
            str(t.get("name")): str(t.get("risk_level", "read"))
            for t in (body.get("pack") or {}).get("tools") or []
        }
        return allowed, risks

    async def aclose(self) -> None:
        await self._client.aclose()
