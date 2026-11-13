"""OpenBao / HashiCorp Vault KV v2 adapter for the secrets port (HTTP API, no SDK)."""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx

from nexiqon_tool_gateway.secrets import SecretNotFound, SecretsUnavailable, check_name


class OpenBaoSecrets:
    def __init__(
        self,
        address: str,
        token: str,
        mount: str = "secret",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=address.rstrip("/"),
            headers={"X-Vault-Token": token},
            timeout=5.0,
            transport=transport,
            trust_env=False,
        )
        self._mount = mount

    def _path(self, kind: str, tenant: uuid.UUID, name: str = "") -> str:
        suffix = f"/{check_name(name)}" if name else ""
        return f"/v1/{self._mount}/{kind}/tenants/{tenant}{suffix}"

    async def _call(self, method: str, path: str, **kw: object) -> httpx.Response:
        try:
            return await self._client.request(method, path, **kw)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            raise SecretsUnavailable("secrets store unreachable") from exc

    async def get(self, tenant: uuid.UUID, name: str) -> str:
        r = await self._call("GET", self._path("data", tenant, name))
        if r.status_code == 404:
            raise SecretNotFound(name)
        if r.status_code >= 400:
            raise SecretsUnavailable(f"secrets store returned {r.status_code}")
        return str(r.json()["data"]["data"]["value"])

    async def put(self, tenant: uuid.UUID, name: str, value: str) -> None:
        r = await self._call(
            "POST", self._path("data", tenant, name), json={"data": {"value": value}}
        )
        if r.status_code >= 400:
            raise SecretsUnavailable(f"secrets store returned {r.status_code}")

    async def delete(self, tenant: uuid.UUID, name: str) -> None:
        r = await self._call("DELETE", self._path("metadata", tenant, name))
        if r.status_code >= 400 and r.status_code != 404:
            raise SecretsUnavailable(f"secrets store returned {r.status_code}")

    async def names(self, tenant: uuid.UUID) -> dict[str, datetime | None]:
        r = await self._call("LIST", self._path("metadata", tenant))
        if r.status_code == 404:
            return {}
        if r.status_code >= 400:
            raise SecretsUnavailable(f"secrets store returned {r.status_code}")
        return {str(k): None for k in r.json()["data"]["keys"] if not str(k).endswith("/")}

    async def aclose(self) -> None:
        await self._client.aclose()
