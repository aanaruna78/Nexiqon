"""Model provider port. Adapters: adapters/openai_compat.py (OpenAI, vLLM, Ollama), anthropic.py, gemini.py."""

from __future__ import annotations

from typing import Protocol

from nexiqon_model_gateway.types import (
    ChatCall,
    ChatOutput,
    EmbedCall,
    EmbedOutput,
    RerankCall,
    RerankOutput,
)


class ProviderError(Exception):
    """A provider call failed. ``retryable`` failures (timeouts, 5xx, 429) may use the fallback profile."""

    def __init__(
        self, provider: str, message: str, *, status: int | None = None, retryable: bool = False
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status
        self.retryable = retryable


class ChatProvider(Protocol):
    name: str

    async def chat(self, call: ChatCall) -> ChatOutput: ...


class EmbeddingProvider(Protocol):
    name: str

    async def embed(self, call: EmbedCall) -> EmbedOutput: ...


class RerankProvider(Protocol):
    name: str

    async def rerank(self, call: RerankCall) -> RerankOutput: ...


def classify_http_error(provider: str, status: int, body: str) -> ProviderError:
    retryable = status == 429 or status >= 500
    return ProviderError(
        provider, f"HTTP {status}: {body[:300]}", status=status, retryable=retryable
    )
