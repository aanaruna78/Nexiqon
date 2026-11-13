"""Shared HTTP plumbing for provider adapters (timeouts and error classification)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexiqon_model_gateway.providers import ProviderError, classify_http_error


async def post_json(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    try:
        response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise ProviderError(provider, "timeout", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(provider, f"connection error: {exc}", retryable=True) from exc
    if response.status_code >= 400:
        raise classify_http_error(provider, response.status_code, response.text)
    try:
        data: dict[str, Any] = response.json()
    except ValueError as exc:
        raise ProviderError(provider, "invalid JSON from provider", retryable=True) from exc
    return data


async def stream_sse(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
) -> AsyncIterator[str]:
    """POST and yield each server-sent event's ``data`` payload (without the ``data:`` prefix)."""
    try:
        async with client.stream(
            "POST", url, json=body, headers={**headers, "accept": "text/event-stream"}
        ) as response:
            if response.status_code >= 400:
                text = (await response.aread()).decode(errors="replace")
                raise classify_http_error(provider, response.status_code, text)
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    yield line[5:].strip()
    except httpx.TimeoutException as exc:
        raise ProviderError(provider, "timeout", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(provider, f"connection error: {exc}", retryable=True) from exc
