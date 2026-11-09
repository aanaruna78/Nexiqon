"""Hybrid search (RT-02), small-to-big expansion (RT-07) and the evidence/abstain decision.

1. embed the query (model gateway, caller's token) -> vector search over chunks of that model;
2. keyword search (OR of query terms, ``simple`` text search: language-neutral, so it works for
   every language including Arabic; stemming per language is a later refinement);
3. reciprocal-rank fusion with the profile's weights, then de-duplication of identical text;
4. optional rerank of the fused candidates;
5. small-to-big: hits are grouped by parent section and expanded to the whole section while the
   context budget allows (sibling hits merge into one passage), citing "Doc > Section, p.N";
6. abstain when the best evidence is below ``min_evidence_score``.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from opentelemetry import metrics

from nexiqon_core.errors import Forbidden
from nexiqon_retrieval.models_client import ModelClient
from nexiqon_retrieval.store import Filters, Hit, Node, VectorStore, strictest

SEPARATOR = " \u203a "
TERM = re.compile(r"\w+", re.UNICODE)
# Very common words that would make every chunk a keyword match (a few languages).
STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "de",
        "do",
        "does",
        "el",
        "en",
        "es",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "la",
        "las",
        "los",
        "of",
        "on",
        "or",
        "que",
        "the",
        "this",
        "to",
        "un",
        "una",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "y",
    ]
)
DEFAULTS: dict[str, Any] = {
    "search": {
        "top_k": 8,
        "vector_weight": 0.6,
        "keyword_weight": 0.4,
        "rerank": False,
        "candidates": 50,
        "rrf_k": 60,
    },
    "small_to_big": {"enabled": True, "max_context_tokens": 3000},
    "min_evidence_score": 0.55,
}
_duration = metrics.get_meter("nexiqon.retrieval").create_histogram(
    "nexiqon.retrieval.search.duration", unit="ms", description="Search latency excluding reranking"
)


def estimate_tokens(text: str) -> int:
    """Model-neutral estimate, the same one ingestion uses (about four characters per token)."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


def cut_to_tokens(text: str, tokens: int) -> str:
    """Longest prefix that ends at a word boundary and, with its ellipsis, fits in ``tokens``."""
    limit = tokens * 4
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]  # leave room for the ellipsis
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip() + "\u2026"


def query_terms(query: str, limit: int = 32) -> list[str]:
    seen: list[str] = []
    for word in TERM.findall(query.lower()):
        if len(word) > 1 and word not in STOP and word not in seen:
            seen.append(word)
    return seen[:limit]


def citation(
    title: str | None, heading_path: list[str], page_start: int | None, page_end: int | None
) -> str:
    label = SEPARATOR.join([t for t in [title, *heading_path] if t]) or "Untitled"
    if page_start is None:
        return label
    pages = f"p.{page_start}" if page_end in (None, page_start) else f"pp.{page_start}-{page_end}"
    return f"{label}, {pages}"


@dataclass
class Passage:
    id: uuid.UUID
    kind: str  # section | chunk
    document_id: uuid.UUID
    collection_id: uuid.UUID
    title: str | None
    heading_path: list[str]
    citation: str
    page_start: int | None
    page_end: int | None
    source_uri: str | None
    text: str
    token_count: int
    score: float
    chunk_ids: list[uuid.UUID]
    matched_chunk_ids: list[uuid.UUID]
    classification: str = "internal"
    truncated: bool = False


@dataclass
class SearchResult:
    passages: list[Passage]
    abstain: bool
    evidence_score: float
    embedding_model: str | None
    reranked: bool
    timings_ms: dict[str, float] = field(default_factory=dict)


@dataclass
class SearchRequest:
    query: str
    filters: Filters
    profile: dict[str, Any]
    model_profile: str
    classification: str
    top_k: int | None = None
    small_to_big: bool | None = None
    rerank: bool | None = None


def merged_profile(profile: dict[str, Any]) -> dict[str, Any]:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for key, value in profile.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        elif key in out:
            out[key] = value
    return out


class Searcher:
    def __init__(self, store: VectorStore, models: ModelClient) -> None:
        if "filter_before_rank" not in store.capabilities:
            raise ValueError("vector store must filter before ranking")
        self.store = store
        self.models = models

    async def search(self, tenant: uuid.UUID, token: str, req: SearchRequest) -> SearchResult:
        profile = merged_profile(req.profile)
        cfg, s2b = profile["search"], profile["small_to_big"]
        top_k = req.top_k or int(cfg["top_k"])
        candidates = max(int(cfg["candidates"]), top_k * 3)
        timings: dict[str, float] = {}
        started = time.perf_counter()

        def lap(name: str, since: float) -> float:
            now = time.perf_counter()
            timings[name] = round((now - since) * 1000, 2)
            return now

        vector, model = await self.models.embed_query(
            token, req.model_profile, req.classification, req.query
        )
        t = lap("embed", started)
        vector_hits = await self.store.vector_search(tenant, vector, model, req.filters, candidates)
        t = lap("vector", t)
        keyword_hits = await self.store.keyword_search(
            tenant, query_terms(req.query), req.filters, candidates
        )
        t = lap("keyword", t)

        fused = self._fuse(
            vector_hits,
            keyword_hits,
            float(cfg["vector_weight"]),
            float(cfg["keyword_weight"]),
            int(cfg["rrf_k"]),
        )
        similarity = {h.id: h.score for h in vector_hits}
        t = lap("fuse", t)

        reranked = False
        rerank_scores: dict[uuid.UUID, float] = {}
        rerank_on = cfg["rerank"] if req.rerank is None else req.rerank
        if rerank_on and fused:
            pool = fused[: min(len(fused), 50)]
            r0 = time.perf_counter()
            # The model gateway routes or refuses by classification, so it must see the true label
            # of the text it receives: the strictest of the request and every candidate (QA2-01).
            label = strictest(req.classification, *(h.classification for h in pool))
            try:
                ranked = await self.models.rerank(
                    token, req.model_profile, label, req.query, [h.text for h in pool], len(pool)
                )
            except Forbidden:
                ranked = None  # this profile may not see these passages: keep the fused order
            timings["rerank"] = round((time.perf_counter() - r0) * 1000, 2)
            if ranked is not None:
                reranked = True
                rerank_scores = {pool[i].id: score for i, score in ranked}
                fused = [pool[i] for i, _ in ranked] + fused[len(pool) :]
                for h in fused:
                    h.score = rerank_scores.get(h.id, 0.0)
            t = time.perf_counter()

        expand = s2b["enabled"] if req.small_to_big is None else req.small_to_big
        if expand:
            passages = await self._expand(
                tenant, fused[: top_k * 3], req.filters, top_k, int(s2b["max_context_tokens"])
            )
        else:
            passages = await self._flat(tenant, fused[:top_k])
        lap("expand", t)

        if reranked:
            evidence = max(rerank_scores.values(), default=0.0)
        else:
            evidence = max(
                (similarity.get(cid, 0.0) for p in passages for cid in p.matched_chunk_ids),
                default=0.0,
            )
        threshold = float(profile["min_evidence_score"])
        total = (time.perf_counter() - started) * 1000 - timings.get("rerank", 0.0)
        timings["total"] = round(total, 2)
        _duration.record(total, {"reranked": reranked})
        return SearchResult(
            passages=passages,
            abstain=not passages or evidence < threshold,
            evidence_score=round(evidence, 4),
            embedding_model=model,
            reranked=reranked,
            timings_ms=timings,
        )

    @staticmethod
    def _fuse(vector: list[Hit], keyword: list[Hit], wv: float, wk: float, k: int) -> list[Hit]:
        """Weighted reciprocal-rank fusion, then drop chunks whose text duplicates a better one."""
        scores: dict[uuid.UUID, float] = {}
        hits: dict[uuid.UUID, Hit] = {}
        for weight, ranked in ((wv, vector), (wk, keyword)):
            for rank, hit in enumerate(ranked, start=1):
                scores[hit.id] = scores.get(hit.id, 0.0) + weight / (k + rank)
                hits.setdefault(hit.id, hit)
        ordered = sorted(hits.values(), key=lambda h: scores[h.id], reverse=True)
        seen: set[str] = set()
        out: list[Hit] = []
        for hit in ordered:
            digest = hashlib.sha256(" ".join(hit.text.lower().split()).encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            out.append(Hit(**{**hit.__dict__, "score": scores[hit.id]}))
        return out

    async def _titles(
        self, tenant: uuid.UUID, document_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        return await self.store.document_titles(tenant, list(document_ids))

    async def _flat(self, tenant: uuid.UUID, hits: list[Hit]) -> list[Passage]:
        titles = await self._titles(tenant, {h.document_id for h in hits})
        return [
            Passage(
                id=h.id,
                kind="chunk",
                document_id=h.document_id,
                collection_id=h.collection_id,
                title=titles.get(h.document_id),
                heading_path=h.heading_path,
                citation=citation(
                    titles.get(h.document_id), h.heading_path, h.page_start, h.page_end
                ),
                page_start=h.page_start,
                page_end=h.page_end,
                source_uri=h.source_uri,
                text=h.text,
                token_count=h.token_count,
                score=h.score,
                chunk_ids=[h.id],
                matched_chunk_ids=[h.id],
                classification=h.classification,
            )
            for h in hits
        ]

    async def _expand(
        self, tenant: uuid.UUID, hits: list[Hit], filters: Filters, top_k: int, budget: int
    ) -> list[Passage]:
        groups: dict[uuid.UUID, list[Hit]] = {}
        for h in hits:  # best-first, so group order follows each section's best hit
            groups.setdefault(h.parent_id or h.id, []).append(h)
        children = await self.store.chunk_children(
            tenant, [p for p in groups if p is not None], filters
        )
        titles = await self._titles(tenant, {h.document_id for h in hits})
        passages: list[Passage] = []
        used = 0
        for parent_id, group in groups.items():
            if len(passages) >= top_k:
                break
            kids = children.get(parent_id, [])
            full = sum(k.token_count for k in kids)
            whole = bool(kids) and used + full <= budget
            truncated = False
            if whole:
                chosen: list[Node | Hit] = list(kids)
            else:  # the whole section does not fit: keep only the matching chunks, in order
                chosen = sorted(group, key=lambda h: h.path)
                if used + sum(h.token_count for h in chosen) > budget:
                    if passages:
                        continue
                    # The best match alone exceeds the budget: cut it at a word boundary so the
                    # cap holds for the first passage too (QA2-06).
                    best = group[0]
                    chosen = [replace(best, text=cut_to_tokens(best.text, budget), token_count=0)]
                    chosen[0].token_count = estimate_tokens(chosen[0].text)
                    truncated = True
            used += sum(c.token_count for c in chosen)
            first = group[0]
            pages = [p for c in chosen for p in (c.page_start, c.page_end) if p is not None]
            is_section = whole or len(chosen) > 1
            heading = list(first.heading_path)
            title = titles.get(first.document_id)
            start, end = (min(pages), max(pages)) if pages else (None, None)
            passages.append(
                Passage(
                    id=parent_id if is_section else first.id,
                    kind="section" if is_section else "chunk",
                    document_id=first.document_id,
                    collection_id=first.collection_id,
                    title=title,
                    heading_path=heading,
                    citation=citation(title, heading, start, end),
                    page_start=start,
                    page_end=end,
                    source_uri=first.source_uri,
                    text="\n\n".join(c.text for c in chosen),
                    token_count=sum(c.token_count for c in chosen),
                    score=first.score,
                    chunk_ids=[c.id for c in chosen],
                    matched_chunk_ids=[h.id for h in group if h.id in {c.id for c in chosen}],
                    classification=strictest(*(c.classification for c in chosen)),
                    truncated=truncated,
                )
            )
        return passages

    async def passage_text(
        self, tenant: uuid.UUID, ids: list[uuid.UUID], filters: Filters
    ) -> dict[uuid.UUID, str]:
        """Text of passages by id (a chunk, or a section's chunks), visible to this caller only."""
        nodes = await self.store.nodes(tenant, ids, filters)
        parents = [n.id for n in nodes if n.kind != "chunk"]
        kids = await self.store.chunk_children(tenant, parents, filters)
        return {
            n.id: n.text if n.kind == "chunk" else "\n\n".join(k.text for k in kids.get(n.id, []))
            for n in nodes
        }
