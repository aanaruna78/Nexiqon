"""Grounded answers (Playground, ST-05; agents use the same contract): search -> prompt -> verify.

The prompt is domain-neutral and lives here, server side. The model sees numbered passages and must
cite them as [n]. Citations are then verified (RT-03) and fabricated or unsupported ones removed.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from nexiqon_core.errors import Forbidden
from nexiqon_retrieval.citations import Citation, Removed, verify
from nexiqon_retrieval.models_client import ModelClient
from nexiqon_retrieval.search import Passage, Searcher, SearchRequest, SearchResult
from nexiqon_retrieval.store import strictest

SYSTEM = (
    "You answer questions using only the numbered sources provided. "
    "Cite every statement with its source number in square brackets, for example [1] or [2][3]. "
    "If the sources do not contain the answer, say that you could not find it in the sources. "
    "Do not use outside knowledge. Answer in the language of the question."
)
MAX_PASSAGE_CHARS = 6000
CANNOT = re.compile(
    r"could not find|cannot find|no (relevant )?information|not (in|contain)", re.IGNORECASE
)


def build_prompt(question: str, passages: list[Passage]) -> str:
    blocks = [
        f"[{i}] {p.citation}\n{p.text[:MAX_PASSAGE_CHARS]}" for i, p in enumerate(passages, start=1)
    ]
    return "Sources:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"


@dataclass
class Answer:
    text: str | None
    abstained: bool
    reason: str | None
    citations: list[tuple[str, Passage]]
    removed: list[Removed]
    search: SearchResult
    model: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)


async def answer(
    searcher: Searcher,
    models: ModelClient,
    tenant: uuid.UUID,
    token: str,
    req: SearchRequest,
    *,
    min_support: float = 0.5,
    max_tokens: int = 800,
) -> Answer:
    found = await searcher.search(tenant, token, req)
    if found.abstain:
        return Answer(
            None, True, "low_evidence" if found.passages else "no_passages", [], [], found
        )
    passages = found.passages
    started = time.perf_counter()
    # The prompt carries every passage, so the call is labelled with the strictest of them; the
    # model gateway then routes it (e.g. restricted -> on-prem) or refuses (QA2-01).
    label = strictest(req.classification, *(p.classification for p in passages))
    try:
        reply = await models.chat(
            token,
            req.model_profile,
            label,
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": build_prompt(req.query, passages)},
            ],
            max_tokens,
        )
    except Forbidden:
        return Answer(None, True, "sensitivity", [], [], found)
    found.timings_ms["generate"] = round((time.perf_counter() - started) * 1000, 2)
    text = str(reply.get("content") or "").strip()
    by_marker = {str(i): p for i, p in enumerate(passages, start=1)}
    markers = sorted(set(re.findall(r"\[(\d{1,3})\]", text)), key=int)
    citations = [Citation(m, by_marker[m].id) for m in markers if m in by_marker]
    texts = {p.id: p.text for p in passages}
    checked = verify(text, citations, texts, min_support)
    kept = [(c.marker, by_marker[c.marker]) for c in checked.citations]
    abstained = checked.abstain or bool(CANNOT.search(checked.answer) and not kept)
    return Answer(
        text=checked.answer,
        abstained=abstained,
        reason="unsupported" if abstained else None,
        citations=kept,
        removed=checked.removed,
        search=found,
        model=dict(reply.get("route") or {}),  # type: ignore[call-overload]
        usage=dict(reply.get("usage") or {}),  # type: ignore[call-overload]
    )
