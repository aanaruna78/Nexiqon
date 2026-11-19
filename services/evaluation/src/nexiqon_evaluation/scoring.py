"""Scorecards (one per run) and the release gate (QA-02). Pure functions, so the rules are tested
without a database or a model."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseOutcome:
    lang: str
    passed: bool
    scores: dict[str, dict[str, Any]]
    latency_ms: int = 0
    tokens: int = 0
    cost: float = 0.0
    error: bool = False


def _percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))]


def scorecard(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    total = len(outcomes)
    passed = sum(o.passed for o in outcomes)
    metrics: dict[str, dict[str, float]] = {}
    sums: dict[str, list[float]] = defaultdict(list)
    for o in outcomes:
        for name, s in o.scores.items():
            sums[name].append(float(s["value"]))
    for name, values in sorted(sums.items()):
        metrics[name] = {"mean": round(sum(values) / len(values), 4), "cases": len(values)}
    langs: dict[str, list[bool]] = defaultdict(list)
    for o in outcomes:
        langs[o.lang].append(o.passed)
    latencies = [o.latency_ms for o in outcomes if not o.error]
    return {
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "errors": sum(o.error for o in outcomes),
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "metrics": metrics,
        "by_lang": {
            lang: {"cases": len(v), "pass_rate": round(sum(v) / len(v), 4)}
            for lang, v in sorted(langs.items())
        },
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "tokens": sum(o.tokens for o in outcomes),
        "cost": round(sum(o.cost for o in outcomes), 6),
    }


@dataclass
class Thresholds:
    min_pass_rate: float = 0.8
    # Largest allowed fall in pass rate, or in any metric, against the live version.
    max_drop: float = 0.05


@dataclass
class GateDecision:
    passed: bool
    reasons: list[dict[str, Any]] = field(default_factory=list)
    deltas: dict[str, float] = field(default_factory=dict)


def gate(
    card: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
    limits: Thresholds,
    *,
    stale: bool = False,
) -> GateDecision:
    """``card``: the candidate version's latest scorecard on the gate's test set (None: never
    evaluated). ``baseline``: the live version's, if any. Reasons are codes Studio translates."""
    if card is None:
        return GateDecision(False, [{"code": "not_evaluated"}])
    if stale:
        return GateDecision(False, [{"code": "stale"}])
    reasons: list[dict[str, Any]] = []
    rate = float(card.get("pass_rate", 0.0))
    if rate < limits.min_pass_rate:
        reasons.append({"code": "below_threshold", "value": rate, "limit": limits.min_pass_rate})
    deltas: dict[str, float] = {}
    if baseline is not None:
        deltas["pass_rate"] = round(rate - float(baseline.get("pass_rate", 0.0)), 4)
        for name, m in (card.get("metrics") or {}).items():
            before = (baseline.get("metrics") or {}).get(name)
            if before is not None:
                deltas[name] = round(float(m["mean"]) - float(before["mean"]), 4)
        for name, delta in deltas.items():
            if delta < -limits.max_drop - 1e-9:
                reasons.append(
                    {"code": "regression", "metric": name, "value": delta, "limit": limits.max_drop}
                )
    return GateDecision(not reasons, reasons, deltas)
