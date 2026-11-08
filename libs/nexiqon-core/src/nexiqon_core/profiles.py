"""Fetches effective profiles (model, retrieval, retention) from config, floors applied there."""

from __future__ import annotations

import time
from typing import Any

import httpx

from nexiqon_core.errors import BadRequest, Forbidden, NexiqonError, NotFound, ServiceUnavailable
from nexiqon_core.tenancy import CONTEXT_HEADER


class ProfileRejected(NexiqonError):
    status, code, title = 409, "security_floor_violation", "Security floor violated"


class ProfileResolver:
    def __init__(
        self,
        base_url: str | None,
        environment: str,
        *,
        kind: str = "model_profile",
        cache_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/") if base_url else None
        self._env = environment
        self._kind = kind
        self._label = kind.replace("_", " ").capitalize()
        self._ttl = cache_seconds
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def _http(self) -> httpx.AsyncClient:
        if self._base is None:
            raise ServiceUnavailable("Config service URL is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base, timeout=5.0, transport=self._transport
            )
        return self._client

    async def get(self, tenant_id: str, context_token: str, name: str) -> dict[str, Any]:
        """Effective profile spec for ``name``. Raises NotFound/ProfileRejected/ServiceUnavailable."""
        key = (tenant_id, name)
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit is not None and hit[0] > now:
            return hit[1]
        try:
            response = await self._http().get(
                f"/v1/resolve/profiles/{self._kind}/{name}",
                params={"environment": self._env},
                headers={CONTEXT_HEADER: context_token},
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Config service unreachable") from exc
        if response.status_code == 200:
            spec: dict[str, Any] = response.json()["profile"]
            if self._ttl > 0:
                self._cache[key] = (now + self._ttl, spec)
            return spec
        detail = _detail(response)
        if response.status_code == 404:
            raise NotFound(f"{self._label} {name!r} not found")
        if response.status_code == 403:
            raise Forbidden(f"Not allowed to use {self._kind} {name!r}")
        if response.status_code == 409:
            raise ProfileRejected(f"{self._label} {name!r}: {detail}")
        if response.status_code < 500:
            raise BadRequest(f"{self._label} {name!r}: {detail}")
        raise ServiceUnavailable(f"Config service error ({response.status_code})")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail") or response.reason_phrase)
    except ValueError:
        return response.reason_phrase
