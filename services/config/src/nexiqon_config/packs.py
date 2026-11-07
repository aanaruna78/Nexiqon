"""Domain Pack file format (YAML, Git-friendly) <-> stored spec. Round-trips losslessly.

apiVersion: nexiqon.dev/v1
kind: DomainPack
metadata: {name, title, description, version, locales}
spec: {vocabulary, intents, graph, prompts, ...}
"""

from __future__ import annotations

from typing import Any

import yaml

from nexiqon_core.errors import BadRequest

API_VERSION = "nexiqon.dev/v1"
KIND = "DomainPack"


def parse_pack(text: str) -> tuple[str, dict[str, Any]]:
    """Return (object name, stored spec)."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BadRequest(f"Invalid YAML: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("apiVersion") != API_VERSION or doc.get("kind") != KIND:
        raise BadRequest(f"Expected apiVersion {API_VERSION} and kind {KIND}")
    meta, spec = doc.get("metadata"), doc.get("spec")
    if not isinstance(meta, dict) or not isinstance(spec, dict) or "name" not in meta:
        raise BadRequest("Pack needs metadata.name and a spec mapping")
    stored_meta = {
        "title": meta.get("title"),
        "description": meta.get("description"),
        "pack_version": meta.get("version"),
        "locales": meta.get("locales"),
    }
    stored = {"metadata": {k: v for k, v in stored_meta.items() if v is not None}, **spec}
    return str(meta["name"]), stored


def render_pack(name: str, stored: dict[str, Any]) -> str:
    meta = dict(stored.get("metadata", {}))
    doc_meta: dict[str, Any] = {"name": name}
    for src, dst in (
        ("title", "title"),
        ("description", "description"),
        ("pack_version", "version"),
        ("locales", "locales"),
    ):
        if src in meta:
            doc_meta[dst] = meta[src]
    spec = {k: v for k, v in stored.items() if k != "metadata"}
    doc = {"apiVersion": API_VERSION, "kind": KIND, "metadata": doc_meta, "spec": spec}
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
