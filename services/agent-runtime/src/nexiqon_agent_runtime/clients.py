"""Calls agent-runtime makes. Model, retrieval and tool calls use the **caller's** token, so the
model gateway, retrieval ACLs and tool authorization apply to the person asking. Only agent
configuration and collection names are read with agent-runtime's own service identity (ADR 0017)."""

from __future__ import annotations

import time
import uuid
from typing import Any, Protocol

import httpx

from nexiqon_core.errors import BadRequest, Forbidden, NexiqonError, NotFound, ServiceUnavailable
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.tenancy import CONTEXT_HEADER


class DownstreamError(NexiqonError):
    status, code, title = 502, "downstream_error", "A platform service failed"


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail") or r.reason_phrase)
    except ValueError:
        return r.reason_phrase


def _raise(r: httpx.Response, what: str) -> None:
    if r.status_code < 400:
        return
    detail = f"{what}: {_detail(r)}"
    if r.status_code == 403:
        raise Forbidden(detail)
    if r.status_code == 404:
        raise NotFound(detail)
    if r.status_code in (400, 409, 422):
        raise BadRequest(detail)
    raise DownstreamError(detail)


class Http:
    def __init__(
        self,
        base_url: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.client = httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False)

    async def call(self, token: str, method: str, path: str, **kw: Any) -> httpx.Response:
        if self.base is None:
            raise ServiceUnavailable(f"Service URL for {path} is not configured")
        try:
            return await self.client.request(
                method, f"{self.base}{path}", headers={CONTEXT_HEADER: token}, **kw
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(f"{path}: {exc}") from exc

    async def aclose(self) -> None:
        await self.client.aclose()


class Models(Http):
    async def chat(
        self,
        token: str,
        *,
        profile: str,
        classification: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "profile": profile,
            "messages": messages,
            "classification": classification,
            "max_tokens": max_tokens,
            "conversation_id": conversation_id,
        }
        if response_schema is not None:
            body["response_schema"] = (
                response_schema  # the gateway picks json_schema or guided JSON
            )
        r = await self.call(token, "POST", "/v1/chat", json=body)
        _raise(r, "model")
        result: dict[str, Any] = r.json()
        return result


class Retrieval(Http):
    async def search(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await self.call(token, "POST", "/v1/search", json=body)
        _raise(r, "retrieval")
        result: dict[str, Any] = r.json()
        return result

    async def verify(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await self.call(token, "POST", "/v1/citations/verify", json=body)
        _raise(r, "citation check")
        result: dict[str, Any] = r.json()
        return result


class ServiceReads:
    """Agent configuration (config) and collection names (ingestion) as agent-runtime itself."""

    def __init__(
        self,
        config: Http,
        ingestion: Http,
        tokens: ServiceTokens,
        environment: str,
        cache_seconds: float = 30.0,
    ) -> None:
        self.config = config
        self.ingestion = ingestion
        self.tokens = tokens
        self.environment = environment
        self.ttl = cache_seconds
        self._agents: dict[tuple[uuid.UUID, str], tuple[float, dict[str, Any]]] = {}
        self._collections: dict[uuid.UUID, tuple[float, dict[str, str]]] = {}

    async def agent(self, tenant: uuid.UUID, name: str) -> dict[str, Any]:
        key = (tenant, name)
        hit = self._agents.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        r = await self.config.call(
            self.tokens.for_tenant(tenant),
            "GET",
            f"/v1/resolve/agents/{name}",
            params={"environment": self.environment},
        )
        _raise(r, f"agent {name!r}")
        resolved: dict[str, Any] = r.json()
        if self.ttl > 0:
            self._agents[key] = (time.monotonic() + self.ttl, resolved)
        return resolved

    async def collection_ids(self, tenant: uuid.UUID, names: list[str]) -> list[str]:
        hit = self._collections.get(tenant)
        if not hit or hit[0] <= time.monotonic() or any(n not in hit[1] for n in names):
            r = await self.ingestion.call(self.tokens.for_tenant(tenant), "GET", "/v1/collections")
            _raise(r, "collections")
            hit = (time.monotonic() + self.ttl, {c["name"]: c["id"] for c in r.json()})
            self._collections[tenant] = hit
        return [hit[1][n] for n in names if n in hit[1]]


class Tools(Protocol):
    """Port to the tool gateway. Calls run with the caller's token."""

    async def describe(self, token: str, name: str) -> dict[str, Any] | None: ...

    async def request_confirmation(
        self,
        token: str,
        name: str,
        *,
        agent: str,
        arguments: dict[str, Any],
        conversation_id: str | None,
    ) -> dict[str, Any]: ...

    async def decide(self, token: str, approval_id: str, approved: bool) -> dict[str, Any]: ...

    async def invoke(
        self,
        token: str,
        name: str,
        *,
        agent: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        approval_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]: ...


def _tool_error(r: httpx.Response) -> dict[str, Any]:
    try:
        body = r.json()
    except ValueError:
        body = {}
    return {
        "ok": False,
        "error": body.get("code") or f"http_{r.status_code}",
        "detail": body.get("detail") or r.reason_phrase,
    }


class HttpTools(Http):
    async def describe(self, token: str, name: str) -> dict[str, Any] | None:
        r = await self.call(token, "GET", f"/v1/tools/{name}")
        if r.status_code in (403, 404):
            return None
        _raise(r, f"tool {name!r}")
        result: dict[str, Any] = r.json()
        return result

    async def request_confirmation(
        self,
        token: str,
        name: str,
        *,
        agent: str,
        arguments: dict[str, Any],
        conversation_id: str | None,
    ) -> dict[str, Any]:
        r = await self.call(
            token,
            "POST",
            f"/v1/tools/{name}/approvals",
            json={"agent": agent, "arguments": arguments, "conversation_id": conversation_id},
        )
        if r.status_code >= 400:
            return _tool_error(r)
        result: dict[str, Any] = r.json()
        return result

    async def decide(self, token: str, approval_id: str, approved: bool) -> dict[str, Any]:
        r = await self.call(
            token, "POST", f"/v1/approvals/{approval_id}/decision", json={"approved": approved}
        )
        if r.status_code >= 400:
            return _tool_error(r)
        result: dict[str, Any] = r.json()
        return result

    async def invoke(
        self,
        token: str,
        name: str,
        *,
        agent: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        approval_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        r = await self.call(
            token,
            "POST",
            f"/v1/tools/{name}/invoke",
            json={
                "agent": agent,
                "arguments": arguments,
                "idempotency_key": idempotency_key,
                "approval_id": approval_id,
                "conversation_id": conversation_id,
            },
        )
        if r.status_code >= 400:
            return _tool_error(r)
        result: dict[str, Any] = r.json()
        return result


class NoTools:
    """When no tool gateway is configured: every tool is reported unavailable (never faked)."""

    async def describe(self, token: str, name: str) -> dict[str, Any] | None:
        return None

    async def request_confirmation(
        self,
        token: str,
        name: str,
        *,
        agent: str,
        arguments: dict[str, Any],
        conversation_id: str | None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "tool_unavailable",
            "detail": f"Tool {name!r} is not available",
        }

    async def decide(self, token: str, approval_id: str, approved: bool) -> dict[str, Any]:
        return {"ok": False, "error": "tool_unavailable"}

    async def invoke(
        self,
        token: str,
        name: str,
        *,
        agent: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        approval_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "tool_unavailable",
            "detail": f"Tool {name!r} is not available",
        }
