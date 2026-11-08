"""Retrieval evaluation harness (RT-05, RT-08).

A gold set lists questions with the document and section that answer them and an evidence phrase.
For each question the harness runs a search and scores:

* **Recall@k**: the expected section is among the top-k passages;
* **MRR**: reciprocal rank of the first correct passage;
* **evidence@k**: the evidence phrase appears in the top-k passages' text (citation support);
* **latency**: P50/P95 of the search's own ``timings_ms.total`` (excludes reranking).

Results are broken down by language. The harness only needs a ``search(question) -> response``
callable, so it runs in-process (CI) or against a live stack (model bake-off, M-07).
"""

from __future__ import annotations

import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Case:
    q: str
    doc: str
    section: str | None
    evidence: str
    lang: str = "en"


@dataclass
class Report:
    k: int
    cases: int
    recall: float
    mrr: float
    evidence: float
    p50_ms: float
    p95_ms: float
    by_language: dict[str, dict[str, float]] = field(default_factory=dict)
    misses: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def load_gold(path: Path) -> list[Case]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Case(**c) for c in raw["cases"]]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _matches(passage: dict[str, Any], case: Case) -> bool:
    uri = str(passage.get("source_uri") or "")
    if not uri.rstrip("/").endswith(case.doc):
        return False
    return case.section is None or case.section in passage.get("heading_path", [])


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


Search = Callable[[str], Awaitable[dict[str, Any]]]


async def evaluate(cases: list[Case], search: Search, k: int = 5) -> Report:
    hits, rr, ev, latencies = [], [], [], []
    per_lang: dict[str, list[tuple[bool, bool]]] = {}
    misses: list[str] = []
    for case in cases:
        response = await search(case.q)
        passages = response["passages"][:k]
        rank = next((i for i, p in enumerate(passages, start=1) if _matches(p, case)), None)
        evidence = any(_norm(case.evidence) in _norm(p["text"]) for p in passages)
        hits.append(rank is not None)
        rr.append(1.0 / rank if rank else 0.0)
        ev.append(evidence)
        latencies.append(float(response.get("timings_ms", {}).get("total", 0.0)))
        per_lang.setdefault(case.lang, []).append((rank is not None, evidence))
        if rank is None:
            misses.append(case.q)
        elif not evidence:
            misses.append(f"evidence: {case.q}")
    n = len(cases) or 1
    return Report(
        k=k,
        cases=len(cases),
        recall=round(sum(hits) / n, 4),
        mrr=round(sum(rr) / n, 4),
        evidence=round(sum(ev) / n, 4),
        p50_ms=round(statistics.median(latencies), 2) if latencies else 0.0,
        p95_ms=round(percentile(latencies, 95), 2),
        by_language={
            lang: {
                "cases": len(rows),
                "recall": round(sum(r for r, _ in rows) / len(rows), 4),
                "evidence": round(sum(e for _, e in rows) / len(rows), 4),
            }
            for lang, rows in sorted(per_lang.items())
        },
        misses=misses,
    )
