"""Layered configuration resolution with provenance and security floors (ARCHITECTURE §6.1).

Layers merge from least to most specific; dicts merge recursively, lists and scalars replace.
Security floors are a conjunction of rules from the platform, the deployment and the tenant, so a
lower layer can only ever add constraints, never remove them. Resolution fails closed on violation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

_MISSING = object()


@dataclass(frozen=True)
class Layer:
    name: str  # e.g. "platform", "tenant", "pack:saas-ka@3", "agent:support@7"
    values: dict[str, Any]


@dataclass(frozen=True)
class FloorRule:
    path: str
    op: str  # equals | subset_of | min | max
    value: Any
    source: str
    reason: str = ""


@dataclass(frozen=True)
class Violation:
    rule: FloorRule
    actual: Any

    @property
    def message(self) -> str:
        r = self.rule
        why = f" ({r.reason})" if r.reason else ""
        return f"{r.path} must satisfy {r.op} {r.value!r} [{r.source}]{why}; got {self.actual!r}"


@dataclass
class Resolved:
    values: dict[str, Any]
    provenance: dict[str, str] = field(default_factory=dict)  # dotted leaf path -> layer name


def merge_layers(layers: Sequence[Layer]) -> Resolved:
    out = Resolved(values={})
    for layer in layers:
        _merge_into(out.values, layer.values, layer.name, "", out.provenance)
    return out


def _merge_into(
    target: dict[str, Any], source: dict[str, Any], layer: str, prefix: str, prov: dict[str, str]
) -> None:
    for key, value in source.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_into(target[key], value, layer, f"{path}.", prov)
        else:
            # Replacing a subtree: drop provenance recorded under it.
            for stale in [p for p in prov if p == path or p.startswith(f"{path}.")]:
                del prov[stale]
            target[key] = _copy(value)
            _record(value, path, layer, prov)


def _record(value: Any, path: str, layer: str, prov: dict[str, str]) -> None:
    if isinstance(value, dict) and value:
        for k, v in value.items():
            _record(v, f"{path}.{k}", layer, prov)
    else:
        prov[path] = layer


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def get_path(values: dict[str, Any], path: str) -> Any:
    node: Any = values
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def check_floors(values: dict[str, Any], rules: Sequence[FloorRule]) -> list[Violation]:
    violations: list[Violation] = []
    for rule in rules:
        actual = get_path(values, rule.path)
        if not _satisfies(rule, actual):
            violations.append(Violation(rule, None if actual is _MISSING else actual))
    return violations


def _satisfies(rule: FloorRule, actual: Any) -> bool:
    if actual is _MISSING:
        # Absent values cannot prove a constraint holds, except an upper bound on a count/size.
        return False
    if rule.op == "equals":
        return bool(actual == rule.value)
    if rule.op == "subset_of":
        allowed = set(rule.value)
        items = actual if isinstance(actual, list) else [actual]
        return all(item in allowed for item in items)
    if rule.op == "min":
        return isinstance(actual, int | float) and actual >= rule.value
    if rule.op == "max":
        return isinstance(actual, int | float) and actual <= rule.value
    raise ValueError(f"unknown floor op {rule.op!r}")


def rules_from(spec: dict[str, Any] | None, source: str) -> list[FloorRule]:
    if not spec:
        return []
    return [
        FloorRule(r["path"], r["op"], r["value"], source, r.get("reason", ""))
        for r in spec.get("rules", [])
    ]
