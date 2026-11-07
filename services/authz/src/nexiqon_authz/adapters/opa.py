"""OPA adapter: evaluates the policy decision over OPA's REST data API."""

from __future__ import annotations

from typing import Any

import httpx

from nexiqon_core.authz import Decision


class OpaClient:
    def __init__(self, base_url: str, decision_path: str, timeout: float = 1.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
        self._path = f"/v1/data/{decision_path.strip('/')}"

    async def evaluate(self, policy_input: dict[str, Any]) -> Decision:
        try:
            response = await self._client.post(self._path, json={"input": policy_input})
            response.raise_for_status()
            result = response.json().get("result")
        except (httpx.HTTPError, ValueError):
            return Decision(allow=False, reasons=["policy engine unavailable"])
        if not isinstance(result, dict):
            # Undefined decision (policy not loaded) fails closed.
            return Decision(allow=False, reasons=["policy decision undefined"])
        return Decision.model_validate(result)

    async def healthy(self) -> bool:
        try:
            return (await self._client.get("/health")).status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
