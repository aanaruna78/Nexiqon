"""Offline development provider: hash embeddings, lexical reranking, extractive answers.

Not a language model. Enabled only when ``allow_offline_provider`` is set (development stacks), so
the whole platform can run end to end without API keys or GPUs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from nexiqon_core.offline_models import EMBED_MODEL, extractive_answer, hash_embed, lexical_scores
from nexiqon_model_gateway.types import (
    ChatCall,
    ChatChunk,
    ChatOutput,
    EmbedCall,
    EmbedOutput,
    RerankCall,
    RerankOutput,
    Usage,
)


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class Offline:
    name = "offline"

    async def chat(self, call: ChatCall) -> ChatOutput:
        prompt = "\n\n".join(m.content or "" for m in call.messages if m.role == "user")
        question = prompt.rsplit("Question:", 1)[-1].strip() if "Question:" in prompt else prompt
        answer = extractive_answer(prompt, question)
        return ChatOutput(
            content=answer,
            usage=Usage(input_tokens=_tokens(prompt), output_tokens=_tokens(answer)),
            model=call.model,
        )

    async def chat_stream(self, call: ChatCall) -> AsyncIterator[ChatChunk]:
        out = await self.chat(call)
        words = (out.content or "").split(" ")
        for i, word in enumerate(words):
            yield ChatChunk(text=word if i == 0 else " " + word)
        yield ChatChunk(usage=out.usage, finish_reason="stop", model=call.model)

    async def embed(self, call: EmbedCall) -> EmbedOutput:
        return EmbedOutput(
            vectors=[hash_embed(t) for t in call.inputs],
            usage=Usage(input_tokens=sum(_tokens(t) for t in call.inputs)),
            model=EMBED_MODEL,
        )

    async def rerank(self, call: RerankCall) -> RerankOutput:
        scores = lexical_scores(call.query, call.documents)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[: call.top_n]
        return RerankOutput(results=ranked, model=call.model)
