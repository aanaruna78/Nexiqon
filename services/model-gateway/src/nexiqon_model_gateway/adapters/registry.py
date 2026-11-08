"""Builds provider adapters from platform credentials, sharing one HTTP connection pool."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from nexiqon_core.errors import BadRequest
from nexiqon_model_gateway.adapters.anthropic import Anthropic
from nexiqon_model_gateway.adapters.gemini import Gemini
from nexiqon_model_gateway.adapters.openai_compat import OpenAICompatible
from nexiqon_model_gateway.providers import (
    ChatProvider,
    EmbeddingProvider,
    RerankProvider,
)
from nexiqon_model_gateway.settings import ProviderCredentials


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


class Providers:
    def __init__(
        self, credentials: ProviderCredentials, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        # Per-call deadlines come from the profile (asyncio.timeout in the gateway).
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=10.0), transport=transport
        )
        openai = OpenAICompatible("openai", _secret(credentials.openai_api_key), self._client)
        compat = OpenAICompatible(
            "openai_compatible", _secret(credentials.openai_compatible_api_key), self._client
        )
        self._chat: dict[str, ChatProvider] = {
            "openai": openai,
            "openai_compatible": compat,
            "anthropic": Anthropic(_secret(credentials.anthropic_api_key), self._client),
            "gemini": Gemini(_secret(credentials.gemini_api_key), self._client),
        }
        self._embed: dict[str, EmbeddingProvider] = {"openai": openai, "openai_compatible": compat}
        self._rerank: dict[str, RerankProvider] = {"openai_compatible": compat}

    def chat(self, name: str) -> ChatProvider:
        return _pick(self._chat, name, "chat")

    def embed(self, name: str) -> EmbeddingProvider:
        return _pick(self._embed, name, "embeddings")

    def rerank(self, name: str) -> RerankProvider:
        return _pick(self._rerank, name, "reranking")

    async def aclose(self) -> None:
        await self._client.aclose()


def _pick[T](table: dict[str, T], name: str, what: str) -> T:
    try:
        return table[name]
    except KeyError:
        raise BadRequest(f"Provider {name!r} does not support {what}") from None
