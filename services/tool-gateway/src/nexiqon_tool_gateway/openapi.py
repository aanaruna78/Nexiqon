"""OpenAPI 3 import (T-03): one tool definition per operation, no code.

Risk follows the HTTP method (GET read, POST/PUT/PATCH write, DELETE high); every definition is
checked against the tool schema by config when it is saved, and stays a draft until published.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import yaml

METHODS = ("get", "post", "put", "patch", "delete")
RISK = {"get": "read", "post": "write", "put": "write", "patch": "write", "delete": "high"}


class OpenApiError(ValueError):
    pass


def _slug(text: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:63] if len(s) >= 2 else f"op-{s}"


def _resolve(node: Any, root: dict[str, Any], depth: int = 0) -> Any:
    if depth > 12:
        return {}
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if not ref.startswith("#/"):
                raise OpenApiError(f"only local $ref are supported ({ref})")
            target: Any = root
            for part in ref[2:].split("/"):
                target = (
                    target.get(part.replace("~1", "/").replace("~0", "~"), {})
                    if isinstance(target, dict)
                    else {}
                )
            return _resolve(target, root, depth + 1)
        return {k: _resolve(v, root, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, root, depth + 1) for v in node]
    return node


def import_spec(
    text: str,
    *,
    base_url: str | None = None,
    operations: list[str] | None = None,
    credential_ref: str | None = None,
    auth_scheme: str = "bearer",
) -> list[dict[str, Any]]:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise OpenApiError(f"not valid YAML or JSON: {exc}") from exc
    if not isinstance(doc, dict) or not str(doc.get("openapi", "")).startswith("3"):
        raise OpenApiError("an OpenAPI 3 document is required")
    server = base_url or next(
        (s.get("url") for s in doc.get("servers") or [] if isinstance(s, dict)), None
    )
    if not server or not str(server).startswith(("https://", "http://")):
        raise OpenApiError("the document has no absolute server URL; pass base_url")
    server = str(server).rstrip("/")
    host = urlsplit(server).hostname
    tools: list[dict[str, Any]] = []
    for path, item in (doc.get("paths") or {}).items():
        item = _resolve(item, doc)
        shared = item.get("parameters") or []
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            op_id = str(op.get("operationId") or f"{method}-{path}")
            if operations and op_id not in operations:
                continue
            properties: dict[str, Any] = {}
            required: list[str] = []
            query: list[str] = []
            for p in [*shared, *(op.get("parameters") or [])]:
                if p.get("in") not in ("path", "query"):
                    continue
                properties[p["name"]] = {
                    **(p.get("schema") or {"type": "string"}),
                    **({"description": p["description"]} if p.get("description") else {}),
                }
                if p.get("required") or p.get("in") == "path":
                    required.append(p["name"])
                if p.get("in") == "query":
                    query.append(p["name"])
            body = (
                ((op.get("requestBody") or {}).get("content") or {})
                .get("application/json", {})
                .get("schema")
            )
            if isinstance(body, dict) and body.get("type") == "object":
                properties.update(body.get("properties") or {})
                required += [r for r in body.get("required") or [] if r not in required]
            responses = op.get("responses") or {}
            ok: dict[str, Any] = next((responses[c] for c in ("200", "201") if c in responses), {})
            output = ((ok.get("content") or {}).get("application/json") or {}).get("schema")
            spec: dict[str, Any] = {
                "description": str(op.get("summary") or op.get("description") or op_id)[:500]
                or op_id,
                "kind": "rest",
                "risk_level": RISK[method],
                "confirmation": "never" if method == "get" else "always",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                    "required": sorted(set(required)),
                },
                "request": {
                    "method": method.upper(),
                    "url_template": server + path,
                    "host_allowlist": [host],
                },
            }
            if query and method != "get":
                spec["request"]["query_params"] = query
            if output:
                spec["output_schema"] = output
            if credential_ref:
                spec["credential_ref"] = f"secret://{credential_ref}"
                spec["request"]["auth"] = {"scheme": auth_scheme}
            if len(spec["description"]) < 5:
                spec["description"] = f"{method.upper()} {path}"
            tools.append({"name": _slug(op_id), "operation_id": op_id, "spec": spec})
    if operations:
        missing = set(operations) - {t["operation_id"] for t in tools}
        if missing:
            raise OpenApiError(f"operations not found: {sorted(missing)}")
    return tools
