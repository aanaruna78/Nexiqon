"""Safe publish (QA-02): before an assistant version with a release gate is published, ask the
evaluation service whether it passed its test set without falling behind the live version.

The question is asked with the publisher's own token, so it needs no extra service identity, and
it fails closed: when evaluation cannot answer, the version is not published (unless overridden).
"""

from __future__ import annotations

from typing import Any

import httpx

from nexiqon_core.errors import Conflict, ServiceUnavailable
from nexiqon_core.tenancy import CONTEXT_HEADER


class ReleaseBlocked(Conflict):
    code, title = "release_gate_failed", "The release gate did not pass"


class Gate:
    def __init__(
        self, base_url: str | None, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.client = httpx.AsyncClient(transport=transport, timeout=15.0, trust_env=False)

    async def check(
        self,
        token: str,
        agent: str,
        version: int,
        spec_hash: str,
        baseline: int | None,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        if self.base is None:
            raise ServiceUnavailable("The evaluation service is not configured")
        body = {
            "version": version,
            "spec_hash": spec_hash,
            "baseline_version": baseline,
            "test_set": rule["test_set"],
            "min_pass_rate": rule.get("min_pass_rate"),
            "max_drop": rule.get("max_drop"),
        }
        try:
            r = await self.client.post(
                f"{self.base}/v1/gates/agents/{agent}/check",
                headers={CONTEXT_HEADER: token},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(f"Evaluation is unavailable: {exc}") from exc
        if r.status_code != 200:
            raise ServiceUnavailable(f"Evaluation answered {r.status_code}")
        result: dict[str, Any] = r.json()
        return result

    async def aclose(self) -> None:
        await self.client.aclose()


def blocked(result: dict[str, Any]) -> ReleaseBlocked:
    error = ReleaseBlocked("Run an evaluation that passes before publishing, or override it")
    error.errors = [dict(r) for r in result.get("reasons") or []]
    return error
