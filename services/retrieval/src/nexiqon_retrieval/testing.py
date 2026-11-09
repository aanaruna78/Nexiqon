"""Deterministic offline embedder (character n-gram hashing) for tests and offline evaluations.

Similar wording gives similar vectors, so retrieval behaviour (fusion, filters, expansion) can be
measured in CI without a model. Real-model quality is measured in the model bake-off (M-07).
"""

from __future__ import annotations

from typing import Any

from nexiqon_core.offline_models import EMBED_MODEL, WORD, extractive_answer, hash_embed

MODEL = EMBED_MODEL


class HashModelClient:
    """ModelClient double: hash embeddings; optional lexical reranker."""

    def __init__(self, rerank_enabled: bool = False) -> None:
        self.rerank_enabled = rerank_enabled
        self.answer: str | None = None  # fixed answer text (e.g. to test fabricated citations)
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

    async def chat(
        self,
        token: str,
        profile: str,
        classification: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> dict[str, object]:
        self.calls.append({"op": "chat", "profile": profile, "messages": messages})
        prompt = messages[-1]["content"]
        answer = self.answer or extractive_answer(prompt, prompt.rsplit("Question:", 1)[-1])
        return {
            "content": answer,
            "route": {"profile": profile, "model": "extractive", "provider": "offline"},
            "usage": {"input_tokens": len(prompt) // 4, "output_tokens": len(answer) // 4},
        }

    async def aclose(self) -> None:
        return None
