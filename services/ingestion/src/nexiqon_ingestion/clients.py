"""Calls to the model gateway (embeddings) and the retrieval index, as ingestion's service identity."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.tenancy import CONTEXT_HEADER


class PermanentError(Exception):
    """Retrying will not help (bad input, refused by policy). ``code`` is shown to users."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class TransientError(Exception):
    """Worth retrying (timeouts, 5xx, 429)."""


def _problem(response: httpx.Response) -> str:
    try:
        body = response.json()
        return str(body.get("detail") or body.get("title") or response.reason_phrase)
    except ValueError:
        return response.reason_phrase


def _raise_for(response: httpx.Response, code: str) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientError(f"{code}: HTTP {response.status_code}")
    raise PermanentError(code, _problem(response))


class ServiceClient:
    def __init__(
        self,
        base_url: str | None,
        tokens: ServiceTokens,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._base = base_url.rstrip("/") if base_url else None
        self._tokens = tokens
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False)

    async def request(
        self, tenant_id: uuid.UUID, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        if self._base is None:
            raise TransientError("service URL is not configured")
        headers = {CONTEXT_HEADER: self._tokens.for_tenant(tenant_id)}
        try:
            return await self._client.request(
                method, f"{self._base}{path}", headers=headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise TransientError(f"{method} {path}: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class Embedder(ServiceClient):
    async def embed(
        self, tenant_id: uuid.UUID, profile: str, classification: str, texts: list[str]
    ) -> tuple[list[list[float]], str]:
        response = await self.request(
            tenant_id,
            "POST",
            "/v1/embeddings",
            json={
                "profile": profile,
                "inputs": texts,
                "input_type": "document",
                "classification": classification,
            },
        )
        _raise_for(response, "embedding_failed")
        body = response.json()
        return body["vectors"], str(body["route"]["model"])


class IndexClient(ServiceClient):
    async def put_document(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID, payload: dict[str, Any]
    ) -> None:
        response = await self.request(
            tenant_id, "PUT", f"/v1/index/documents/{document_id}", json=payload
        )
        _raise_for(response, "index_failed")

    async def delete_document(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> None:
        response = await self.request(tenant_id, "DELETE", f"/v1/index/documents/{document_id}")
        _raise_for(response, "index_failed")

    async def delete_collection(self, tenant_id: uuid.UUID, collection_id: uuid.UUID) -> None:
        response = await self.request(tenant_id, "DELETE", f"/v1/index/collections/{collection_id}")
        _raise_for(response, "index_failed")
