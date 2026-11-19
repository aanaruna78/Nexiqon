"""Calls to agent-runtime as evaluation's own identity (``service:evaluation``)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from nexiqon_core.errors import ServiceUnavailable
from nexiqon_core.tenancy import CONTEXT_HEADER
from nexiqon_sdk import EvalCitation, EvalObservation


class AgentRuntime:
    def __init__(
        self,
        base_url: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.client = httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False)

    async def ask(
        self, token: str, agent: str, version: int, thread_id: str, question: str, lang: str
    ) -> tuple[EvalObservation, str | None]:
        """One fresh turn on its own thread; returns what was seen and the agent run id."""
        if self.base is None:
            raise ServiceUnavailable("agent-runtime URL is not configured")
        started = time.monotonic()
        try:
            r = await self.client.post(
                f"{self.base}/v1/agents/{agent}/runs",
                headers={CONTEXT_HEADER: token},
                json={
                    "thread_id": thread_id,
                    "input": question,
                    "locale": lang,
                    "version": version,
                },
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(f"agent-runtime: {exc}") from exc
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code >= 500 or r.status_code == 429:
            raise ServiceUnavailable(f"agent-runtime answered {r.status_code}")
        if r.status_code >= 400:
            detail = _detail(r)
            return EvalObservation(
                answer="", abstained=True, latency_ms=latency, error=detail
            ), None
        body: dict[str, Any] = r.json()
        return observe(body, latency), str(body.get("run_id") or "") or None

    async def aclose(self) -> None:
        await self.client.aclose()


class Config:
    """Reads an assistant version's content hash (as ``service:evaluation``)."""

    def __init__(
        self, base_url: str | None, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.client = httpx.AsyncClient(transport=transport, timeout=15.0, trust_env=False)

    async def spec_hash(self, token: str, agent: str, version: int) -> str | None:
        if self.base is None:
            raise ServiceUnavailable("config URL is not configured")
        try:
            r = await self.client.get(
                f"{self.base}/v1/objects/agent/{agent}/versions/{version}",
                headers={CONTEXT_HEADER: token},
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(f"config: {exc}") from exc
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise ServiceUnavailable(f"config answered {r.status_code}")
        return str(r.json()["spec_hash"])

    async def aclose(self) -> None:
        await self.client.aclose()


def _detail(r: httpx.Response) -> str:
    try:
        data = r.json()
        return f"{r.status_code} {data.get('code') or ''}: {data.get('detail') or data.get('title') or ''}"[
            :500
        ]
    except ValueError:
        return f"{r.status_code}"


def _tokens(usage: dict[str, Any]) -> int:
    return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)


def observe(body: dict[str, Any], latency_ms: int) -> EvalObservation:
    usage = body.get("usage") or {}
    answer = body.get("answer")
    if answer is None:
        interrupt = body.get("interrupt") or {}
        text = str(interrupt.get("question") or interrupt.get("summary") or "")
        return EvalObservation(
            answer=text,
            abstained=not text,
            kind="interrupted" if interrupt else body.get("status"),
            latency_ms=latency_ms,
            tokens=_tokens(usage),
            cost=float(usage.get("cost_usd") or 0.0),
            error=body.get("error"),
        )
    return EvalObservation(
        answer=str(answer.get("text") or ""),
        abstained=bool(answer.get("abstained")),
        kind=answer.get("kind"),
        citations=tuple(
            EvalCitation(citation=str(c.get("citation") or ""), source_uri=c.get("source_uri"))
            for c in answer.get("citations") or []
        ),
        latency_ms=latency_ms,
        tokens=_tokens(usage),
        cost=float(usage.get("cost_usd") or 0.0),
        error=body.get("error"),
    )
