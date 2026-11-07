"""Data-plane client for signed configuration snapshots (CF-05, hybrid mode).

The data plane pulls ``GET {config}/v1/snapshots/{environment}`` with the tenant's context token,
verifies the control plane's signature and the body digest, and caches the verified payload on
disk. If the control plane is unreachable it keeps serving the last verified snapshot; a cached
file is re-verified on every load, so a tampered cache is rejected.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from nexiqon_core.errors import ServiceUnavailable, Unauthorized
from nexiqon_core.signing import canonical_digest, verify
from nexiqon_core.tenancy import CONTEXT_HEADER


@dataclass(frozen=True)
class Snapshot:
    tenant_id: str
    environment: str
    digest: str
    body: dict[str, Any]
    source: Literal["remote", "cache"]
    fetched_at: float

    def agent(self, name: str) -> dict[str, Any]:
        agent: dict[str, Any] = self.body["agents"][name]
        return agent


class SnapshotClient:
    def __init__(
        self,
        base_url: str,
        environment: str,
        public_keys: dict[str, str],
        cache_dir: Path,
        *,
        timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )
        self._env = environment
        self._keys = public_keys
        self._dir = cache_dir

    def _path(self, tenant_id: str) -> Path:
        return self._dir / f"{tenant_id}.{self._env}.json"

    def _verify(
        self, payload: dict[str, Any], tenant_id: str, source: Literal["remote", "cache"]
    ) -> Snapshot:
        body = payload.get("snapshot")
        if not isinstance(body, dict):
            raise Unauthorized("Malformed snapshot")
        claims = verify(str(payload.get("signature", "")), self._keys)
        digest = canonical_digest(body)
        if not (
            claims.get("digest") == digest == payload.get("digest")
            and claims.get("tenant_id") == tenant_id == body.get("tenant_id")
            and claims.get("environment") == self._env == body.get("environment")
        ):
            raise Unauthorized("Snapshot signature does not match its content")
        return Snapshot(tenant_id, self._env, digest, body, source, time.time())

    def load_cached(self, tenant_id: str) -> Snapshot | None:
        path = self._path(tenant_id)
        if not path.exists():
            return None
        return self._verify(json.loads(path.read_text()), tenant_id, "cache")

    def _store(self, tenant_id: str, payload: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, self._path(tenant_id))  # atomic

    async def get(self, context_token: str, tenant_id: str) -> Snapshot:
        cached = self.load_cached(tenant_id)
        headers = {CONTEXT_HEADER: context_token}
        if cached is not None:
            headers["If-None-Match"] = f'"{cached.digest}"'
        try:
            response = await self._client.get(f"/v1/snapshots/{self._env}", headers=headers)
        except httpx.HTTPError as exc:
            if cached is not None:
                return cached
            raise ServiceUnavailable("Control plane unreachable and no cached snapshot") from exc
        if response.status_code == 304 and cached is not None:
            return cached
        if response.status_code == 200:
            payload = response.json()
            snapshot = self._verify(payload, tenant_id, "remote")
            self._store(tenant_id, payload)
            return snapshot
        if response.status_code >= 500 and cached is not None:
            return cached
        raise ServiceUnavailable(f"Snapshot request failed ({response.status_code})")

    async def aclose(self) -> None:
        await self._client.aclose()
