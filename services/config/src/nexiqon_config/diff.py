"""Structural JSON diff for version comparison in Studio (config diff next to score diff)."""

from __future__ import annotations

from typing import Any


def diff(old: Any, new: Any, path: str = "") -> list[dict[str, Any]]:
    """Return operations {op: add|remove|replace, path, old?, new?} turning ``old`` into ``new``."""
    if isinstance(old, dict) and isinstance(new, dict):
        ops: list[dict[str, Any]] = []
        for key in sorted(set(old) | set(new)):
            sub = f"{path}.{key}" if path else str(key)
            if key not in new:
                ops.append({"op": "remove", "path": sub, "old": old[key]})
            elif key not in old:
                ops.append({"op": "add", "path": sub, "new": new[key]})
            else:
                ops += diff(old[key], new[key], sub)
        return ops
    if old != new:
        return [{"op": "replace", "path": path, "old": old, "new": new}]
    return []
