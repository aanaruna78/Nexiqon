"""Query embeddings and reranking through the model gateway, as the *caller* (their token)."""

from __future__ import annotations

from typing import Protocol

import httpx

from nexiqon_core.errors import BadRequest, Forbidden, NexiqonError, ServiceUnavailable
from nexiqon_core.tenancy import CONTEXT_HEADER


class ModelUnavailable(NexiqonError):
    status, code, title = 502, "model_unavailable", "Model call failed"


class ModelClient(Protocol):
    async def embed_query(
        self, token: str, profile: str, classification: str, query: str
    ) -> tuple[list[float], str]:
        """Return (vector, embedding model name)."""
        ...

    async def rerank(
        self,
        token: str,
        profile: str,
        classification: str,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[tuple[int, float]] | None:
        """Best-first (index, score); None when the profile has no reranker."""
        ...

    async def aclose(self) -> None: ...


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail") or r.reason_phrase)
    except ValueError:
        return r.reason_phrase


class GatewayModelClient:
    def __init__(
        self, base_url: str | None, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._base = base_url.rstrip("/") if base_url else None
        self._client = httpx.AsyncClient(transport=transport, timeout=30.0, trust_env=False)

    async def _post(self, token: str, path: str, body: dict[str, object]) -> httpx.Response:
        if self._base is None:
            raise ServiceUnavailable("Model gateway URL is not configured")
        try:
            return await self._client.post(
                f"{self._base}{path}", json=body, headers={CONTEXT_HEADER: token}
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Model gateway unreachable") from exc

    async def embed_query(
        self, token: str, profile: str, classification: str, query: str
    ) -> tuple[list[float], str]:
        r = await self._post(
            token,
            "/v1/embeddings",
            {
                "profile": profile,
                "inputs": [query],
                "input_type": "query",
                "classification": classification,
            },
        )
        if r.status_code == 403:
            raise Forbidden(_detail(r))
        if r.status_code >= 400:
            raise (BadRequest if r.status_code < 500 else ModelUnavailable)(_detail(r))
        body = r.json()
        return body["vectors"][0], str(body["route"]["model"])

    async def rerank(
        self,
        token: str,
        profile: str,
        classification: str,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[tuple[int, float]] | None:
        r = await self._post(
            token,
            "/v1/rerank",
            {
                "profile": profile,
                "query": query,
                "documents": documents,
                "top_n": top_n,
                "classification": classification,
            },
        )
        if r.status_code == 400:
            return None  # profile without a reranker: search proceeds without one
        if r.status_code >= 400:
            raise (Forbidden if r.status_code == 403 else ModelUnavailable)(_detail(r))
        return [(int(x["index"]), float(x["score"])) for x in r.json()["results"]]

    async def aclose(self) -> None:
        await self._client.aclose()
