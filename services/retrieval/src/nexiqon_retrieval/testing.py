"""Deterministic offline embedder (character n-gram hashing) for tests and offline evaluations.

Similar wording gives similar vectors, so retrieval behaviour (fusion, filters, expansion) can be
measured in CI without a model. Real-model quality is measured in the model bake-off (M-07).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

DIMS = 1024
MODEL = "hash-ngram-1024"
WORD = re.compile(r"\w+", re.UNICODE)


def hash_embed(text: str) -> list[float]:
    vec = [0.0] * DIMS
    for word in WORD.findall(text.lower()):
        padded = f"#{word}#"
        grams = [padded[i : i + 3] for i in range(max(1, len(padded) - 2))] + [f"w:{word}"]
        for gram in grams:
            h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "big")
            vec[h % DIMS] += 1.0 if (h >> 63) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class HashModelClient:
    """ModelClient double: hash embeddings; optional lexical reranker."""

    def __init__(self, rerank_enabled: bool = False) -> None:
        self.rerank_enabled = rerank_enabled
        self.calls: list[dict[str, Any]] = []

    async def embed_query(
        self, token: str, profile: str, classification: str, query: str
    ) -> tuple[list[float], str]:
        self.calls.append({"op": "embed", "profile": profile, "classification": classification})
        return hash_embed(query), MODEL

    async def rerank(
        self,
        token: str,
        profile: str,
        classification: str,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[tuple[int, float]] | None:
        self.calls.append({"op": "rerank", "profile": profile, "n": len(documents)})
        if not self.rerank_enabled:
            return None
        q = set(WORD.findall(query.lower()))
        scored = [
            (i, len(q & set(WORD.findall(d.lower()))) / (len(q) or 1))
            for i, d in enumerate(documents)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    async def aclose(self) -> None:
        return None
