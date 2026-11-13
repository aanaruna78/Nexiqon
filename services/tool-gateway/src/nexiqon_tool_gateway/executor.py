"""Declarative REST execution (T-03): build the request from the tool definition, send it through
the SSRF-safe pinned fetcher, minimise the result.

* path placeholders ``{name}`` are filled from arguments, URL-encoded, so they cannot add path
  segments, a query or another host;
* ``{caller.actor_id}`` / ``{caller.tenant_id}`` are filled only from the verified caller;
* the final host must be in the tool's ``host_allowlist``; redirects are not followed;
* credentials are applied here, at the last moment, and scrubbed from anything returned.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from nexiqon_core.fetch import FetchBlocked, FetchFailed, FetchTooLarge, SafeFetcher
from nexiqon_tool_gateway.registry import ToolDef

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")
REDACTED = "[redacted]"


class ToolFailure(Exception):
    def __init__(
        self, code: str, detail: str, *, http_status: int | None = None, retryable: bool = False
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.http_status = http_status
        self.retryable = retryable


@dataclass
class Prepared:
    method: str
    url: str
    query: dict[str, Any]
    body: dict[str, Any] | None
    headers: dict[str, str]  # without credentials


def prepare(
    tool: ToolDef, arguments: dict[str, Any], *, actor_id: str, tenant: uuid.UUID, allow_http: bool
) -> Prepared:
    request = tool.spec["request"]
    template = str(request["url_template"])
    caller = {"caller.actor_id": actor_id, "caller.tenant_id": str(tenant)}
    used: set[str] = set()

    def fill(match: re.Match[str]) -> str:
        key = match.group(1)
        if key.startswith("caller."):
            if key not in caller:
                raise ToolFailure("bad_definition", f"unknown caller placeholder {key!r}")
            return quote(caller[key], safe="")
        if key not in arguments:
            raise ToolFailure("invalid_arguments", f"missing argument {key!r}")
        used.add(key)
        return quote(str(arguments[key]), safe="")

    url = PLACEHOLDER.sub(fill, template)
    parts = urlsplit(url)
    if parts.scheme != "https" and not (allow_http and parts.scheme == "http"):
        raise ToolFailure("egress_blocked", "tools must use https")
    allowed = {h.lower() for h in request.get("host_allowlist") or []}
    if (parts.hostname or "").lower() not in allowed:
        raise ToolFailure(
            "egress_blocked", f"host {parts.hostname!r} is not on this tool's allowlist"
        )
    rest = {k: v for k, v in arguments.items() if k not in used}
    method = str(request["method"])
    query_names = set(request.get("query_params") or [])
    if method in ("GET", "DELETE"):
        query, body = rest, None
    else:
        query = {k: v for k, v in rest.items() if k in query_names}
        body = {k: v for k, v in rest.items() if k not in query_names}
    headers = {str(k): str(v) for k, v in (request.get("headers") or {}).items()}
    return Prepared(method=method, url=url, query=query, body=body, headers=headers)


def _auth_headers(tool: ToolDef, secret: str | None) -> dict[str, str]:
    auth = tool.spec.get("request", {}).get("auth")
    if not auth or secret is None:
        return {}
    scheme = auth["scheme"]
    if scheme == "bearer":
        return {"authorization": f"Bearer {secret}"}
    if scheme == "basic":
        return {"authorization": "Basic " + base64.b64encode(secret.encode()).decode()}
    return {str(auth.get("header") or "x-api-key"): secret}


def scrub(value: Any, secret: str | None) -> Any:
    """Remove any echo of the credential from text or JSON (errors and results)."""
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, REDACTED)
    if isinstance(value, list):
        return [scrub(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v, secret) for k, v in value.items()}
    return value


def minimise(value: Any, schema: dict[str, Any] | None) -> Any:
    """Keep only what the output schema declares (objects: properties; arrays: items)."""
    if not schema:
        return value
    if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
        props: dict[str, Any] = schema["properties"]
        return {k: minimise(v, props[k]) for k, v in value.items() if k in props}
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [minimise(v, schema["items"]) for v in value]
    return value


def cap(value: Any, max_bytes: int) -> tuple[Any, bool]:
    text = json.dumps(value, ensure_ascii=False)
    if len(text.encode()) <= max_bytes:
        return value, False
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            if len(json.dumps([*out, item], ensure_ascii=False).encode()) > max_bytes:
                break
            out.append(item)
        return out, True
    return {"truncated_text": text.encode()[: max_bytes - 64].decode(errors="ignore")}, True


async def execute(
    fetcher: SafeFetcher,
    tool: ToolDef,
    prepared: Prepared,
    *,
    secret: str | None,
    timeout_ms: int,
    max_result_bytes: int,
) -> tuple[Any, int, bool]:
    url = prepared.url + (
        ("&" if "?" in prepared.url else "?") + urlencode(prepared.query, doseq=True)
        if prepared.query
        else ""
    )
    headers = {"accept": "application/json", **prepared.headers, **_auth_headers(tool, secret)}
    content = None
    if prepared.body is not None:
        headers["content-type"] = "application/json"
        content = json.dumps(prepared.body).encode()
    try:
        response = await fetcher.request(
            prepared.method,
            url,
            headers=headers,
            content=content,
            timeout_seconds=timeout_ms / 1000,
        )
    except FetchBlocked as exc:
        raise ToolFailure("egress_blocked", scrub(str(exc.detail or exc), secret)) from exc
    except FetchTooLarge as exc:
        raise ToolFailure("result_too_large", "the tool returned more data than allowed") from exc
    except FetchFailed as exc:
        raise ToolFailure(
            "unreachable", scrub(str(exc.detail or exc), secret), retryable=True
        ) from exc
    status = response.status
    if 300 <= status < 400:
        raise ToolFailure(
            "redirect_refused",
            "the tool tried to redirect; redirects are not followed",
            http_status=status,
        )
    try:
        payload: Any = json.loads(response.content) if response.content else None
    except ValueError:
        payload = response.content.decode(errors="replace")[:2000]
    payload = scrub(payload, secret)
    if status >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise ToolFailure(
            "upstream_error",
            f"the tool returned HTTP {status}: {str(detail)[:300]}",
            http_status=status,
            retryable=status >= 500 or status == 429,
        )
    result, truncated = cap(minimise(payload, tool.spec.get("output_schema")), max_result_bytes)
    return result, status, truncated
