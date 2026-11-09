"""What connectors get from the platform for one run (implements nexiqon_sdk.ConnectorContext)."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from nexiqon_core.blobs import BlobStore
from nexiqon_core.fetch import SafeFetcher


class MissingCredentials(Exception):
    pass


class Context:
    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        http: SafeFetcher,
        blobs: BlobStore,
        scratch: Path,
        credentials: dict[str, dict[str, str]],
        max_items: int,
        max_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.http = http
        self.user_agent = http.policy.user_agent
        self.max_items = max_items
        self.max_bytes = max_bytes
        self.transport = transport  # for adapters' own HTTP clients (tests inject a mock)
        self.state: dict[str, Any] = {}
        self.warnings: list[tuple[str, str]] = []
        # Set when discovery could not see everything (timeouts, 5xx, blocked robots.txt...): the
        # run then must not treat missing items as removed from the source (QA2-03).
        self.incomplete = False
        self._blobs = blobs
        self._scratch = scratch
        self._credentials = credentials

    async def read_upload(self, key: str) -> bytes:
        if not key.startswith(f"t/{self.tenant_id}/"):
            raise PermissionError("upload belongs to another tenant")
        return await self._blobs.get(key)

    async def check_host(self, url: str) -> str:
        _, address = await self.http.check(url)
        return address

    def credentials(self, name: str) -> dict[str, str]:
        """Operator-provisioned secrets for this tenant (``<tenant_id>/<name>`` in settings)."""
        found = self._credentials.get(f"{self.tenant_id}/{name}")
        if found is None:
            raise MissingCredentials(
                f"No credentials named {name!r} are configured for this workspace"
            )
        return found

    def workdir(self, name: str) -> str:
        path = self._scratch / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def warn(self, uri: str, message: str) -> None:
        self.warnings.append((uri, message[:300]))

    def mark_incomplete(self, uri: str, message: str) -> None:
        self.incomplete = True
        self.warn(uri, message)

    # Pages fetched during discovery, reused by fetch on the same worker (avoids a second download).
    def _cache_path(self, uri: str) -> Path:
        return Path(self.workdir("pages")) / hashlib.sha256(uri.encode()).hexdigest()

    def cache_put(self, uri: str, data: bytes, media_type: str, version: str | None) -> None:
        path = self._cache_path(uri)
        path.write_bytes(data)
        path.with_suffix(".json").write_text(
            json.dumps({"media_type": media_type, "version": version})
        )

    def cache_get(self, uri: str) -> tuple[bytes, str, str | None] | None:
        path = self._cache_path(uri)
        meta = path.with_suffix(".json")
        if not (path.exists() and meta.exists()):
            return None
        info = json.loads(meta.read_text())
        return path.read_bytes(), str(info["media_type"]), info["version"]
