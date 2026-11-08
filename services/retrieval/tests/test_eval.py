"""Retrieval quality gate (RT-05, RT-07, RT-08) on the SaaS Knowledge Assistant gold set.

Offline hash embeddings make this a test of the retrieval machinery (fusion, filters, tree
expansion, latency), not of a model; model quality is measured in the bake-off (M-07).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from nexiqon_retrieval.evaluation import evaluate, load_gold

from .conftest import SearchStack

pytestmark = pytest.mark.integration
PACK = Path(__file__).resolve().parents[3] / "packs" / "saas-knowledge-assistant" / "eval"
RECALL_AT_5_FLOOR = 0.8
P95_BUDGET_MS = 100.0


async def run(stack: SearchStack, **options: Any) -> Any:
    async def search(question: str) -> dict[str, Any]:
        return stack.search(question, top_k=5, **options)

    return await evaluate(load_gold(PACK / "gold.yaml"), search, k=5)


def test_gold_set_recall_latency_and_small_to_big_baseline(stack: SearchStack) -> None:
    import asyncio

    for path in sorted((PACK / "corpus").glob("*.md")):
        stack.index(path.read_text(encoding="utf-8"), f"upload://{path.name}", max_tokens=20)
    stack.search("warm up")  # first query pays connection set-up
    tree = asyncio.run(run(stack))
    flat = asyncio.run(run(stack, small_to_big=False))
    report = {"small_to_big": tree.as_dict(), "flat": flat.as_dict()}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if os.environ.get("NEXIQON_EVAL_REPORT"):
        Path(os.environ["NEXIQON_EVAL_REPORT"]).write_text(
            json.dumps(report, indent=2, ensure_ascii=False)
        )
    assert tree.recall >= RECALL_AT_5_FLOOR, tree.misses
    assert tree.recall >= flat.recall  # RT-07: never worse than the flat baseline
    assert tree.evidence >= flat.evidence
    for lang, scores in tree.by_language.items():
        assert scores["recall"] >= 0.66, (lang, scores)
    assert tree.p95_ms < P95_BUDGET_MS  # RT-08 (excludes reranking; embeddings are local here)
