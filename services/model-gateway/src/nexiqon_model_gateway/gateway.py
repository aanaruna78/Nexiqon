"""The model gateway: one entry point for chat, embeddings and reranking.

For every call it resolves the tenant's model profile (security floors are applied by config),
routes by data classification, refuses to send forbidden data to cloud providers, enforces
budgets, redacts personal data for cloud providers, falls back on retryable failures (chat only),
and records usage without storing any prompt or completion text.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import BadRequest, Forbidden, NexiqonError, ServiceUnavailable
from nexiqon_core.events import add_event
from nexiqon_core.tenancy import TenantContext
from nexiqon_model_gateway.adapters.registry import Providers
from nexiqon_model_gateway.models import Outbox, UsageRecord
from nexiqon_model_gateway.pricing import PriceBook
from nexiqon_model_gateway.providers import ChatProvider, ProviderError
from nexiqon_model_gateway.redaction import Redactor
from nexiqon_model_gateway.resolver import ProfileRejected, ProfileResolver
from nexiqon_model_gateway.settings import Classification, ServiceSettings
from nexiqon_model_gateway.types import (
    ChatCall,
    ChatOutput,
    EmbedCall,
    Message,
    RerankCall,
    ToolCall,
    ToolSpec,
    Usage,
)

log = structlog.get_logger(__name__)
SERVICE = "model-gateway"
USAGE_EVENT = "nexiqon.model-gateway.usage.recorded"
MAX_ROUTING_HOPS = 3
# Providers that keep data inside the deployment.
ON_PREM_PROVIDERS = {"openai_compatible", "offline"}


class ProviderFailed(NexiqonError):
    status, code, title = 502, "provider_error", "Model provider failed"


class BudgetExceeded(NexiqonError):
    status, code, title = 429, "budget_exceeded", "Budget exceeded"


@dataclass
class Target:
    """The profile a call actually uses, and how it was chosen."""

    name: str
    spec: dict[str, Any]
    requested: str
    fallback: bool = False

    @property
    def location(self) -> str:
        return str(self.spec["data_policy"]["location"])

    @property
    def redacts(self) -> bool:
        return bool(self.spec.get("redact_pii", self.location == "cloud"))


@dataclass
class Caller:
    ctx: TenantContext
    token: str
    classification: Classification = "internal"
    conversation_id: str | None = None


@dataclass
class ChatRequest:
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    max_tokens: int | None = None
    temperature: float | None = None


@dataclass
class Result[T]:
    output: T
    target: Target
    provider: str
    model: str
    usage: Usage
    cost_usd: Decimal
    redacted: bool


class Gateway:
    def __init__(
        self,
        settings: ServiceSettings,
        resolver: ProfileResolver,
        providers: Providers,
        prices: PriceBook,
        db: TenantSessionFactory | None,
    ) -> None:
        self.settings = settings
        self.resolver = resolver
        self.providers = providers
        self.prices = prices
        self.db = db

    # ------------------------------------------------------------------ profile selection

    async def _profile(self, caller: Caller, name: str) -> dict[str, Any]:
        return await self.resolver.get(str(caller.ctx.tenant_id), caller.token, name)

    async def route(self, caller: Caller, requested: str) -> Target:
        """Follow the profile's routing rules for the caller's data classification."""
        name, spec, seen = requested, await self._profile(caller, requested), {requested}
        for _ in range(MAX_ROUTING_HOPS):
            nxt = _routed_to(spec, caller.classification)
            if nxt is None or nxt == name:
                break
            if nxt in seen:
                raise ProfileRejected(f"Routing loop between model profiles: {sorted(seen)}")
            seen.add(nxt)
            name, spec = nxt, await self._profile(caller, nxt)
        else:
            raise ProfileRejected(f"Routing from {requested!r} exceeds {MAX_ROUTING_HOPS} hops")
        target = Target(name, spec, requested)
        self._check(target, caller.classification)
        return target

    def _check(self, target: Target, classification: str) -> None:
        if (
            target.location == "cloud"
            and classification in self.settings.cloud_forbidden_classifications
        ):
            raise Forbidden(
                f"{classification} data may not be sent to cloud model profile {target.name!r}"
            )
        if target.location == "on_prem":
            sections = [target.spec.get("chat"), target.spec.get("embedding")]
            reranker = target.spec.get("reranker") or {}
            if reranker.get("enabled"):
                sections.append(reranker)
            for section in sections:
                if section and section.get("provider") not in ON_PREM_PROVIDERS:
                    raise ProfileRejected(
                        f"Profile {target.name!r} is on-prem but uses provider "
                        f"{section.get('provider')!r}"
                    )

    # ------------------------------------------------------------------ budgets and usage

    async def _check_budget(self, caller: Caller, target: Target) -> None:
        budgets = target.spec.get("budgets") or {}
        if not budgets:
            return
        if self.db is None:
            raise ServiceUnavailable("Budgets are configured but usage storage is unavailable")
        now = datetime.now(UTC)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        async with self.db.session(caller.ctx) as s:
            if "monthly_usd" in budgets:
                spent = await s.scalar(
                    select(func.coalesce(func.sum(UsageRecord.cost_usd), 0)).where(
                        UsageRecord.profile == target.name, UsageRecord.created_at >= month_start
                    )
                )
                if Decimal(spent or 0) >= Decimal(str(budgets["monthly_usd"])):
                    raise BudgetExceeded(
                        f"Monthly budget of {budgets['monthly_usd']} USD for model profile "
                        f"{target.name!r} is used up"
                    )
            limit = budgets.get("per_conversation_tokens")
            if limit and caller.conversation_id:
                used = await s.scalar(
                    select(
                        func.coalesce(
                            func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0
                        )
                    ).where(UsageRecord.conversation_id == caller.conversation_id)
                )
                if int(used or 0) >= int(limit):
                    raise BudgetExceeded(f"Conversation token budget of {limit} is used up")

    async def _record(
        self,
        caller: Caller,
        operation: str,
        target: Target,
        provider: str,
        model: str,
        usage: Usage,
        redacted: bool,
        started: float,
    ) -> Decimal:
        cost = self.prices.cost(provider, model, usage.input_tokens, usage.output_tokens)
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "model_call",
            operation=operation,
            profile=target.name,
            provider=provider,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency_ms,
            fallback=target.fallback,
        )
        if self.db is None:
            return cost
        async with self.db.session(caller.ctx) as s:
            record = UsageRecord(
                tenant_id=caller.ctx.tenant_id,
                actor_id=caller.ctx.actor_id,
                operation=operation,
                profile=target.name,
                requested_profile=target.requested,
                provider=provider,
                model=model,
                classification=caller.classification,
                conversation_id=caller.conversation_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=cost,
                priced=self.prices.is_priced(provider, model),
                fallback_used=target.fallback,
                redacted=redacted,
                latency_ms=latency_ms,
            )
            s.add(record)
            add_event(
                s,
                Outbox,
                caller.ctx,
                source=SERVICE,
                type=USAGE_EVENT,
                subject=target.name,
                data={
                    "operation": operation,
                    "profile": target.name,
                    "requested_profile": target.requested,
                    "provider": provider,
                    "model": model,
                    "classification": caller.classification,
                    "conversation_id": caller.conversation_id,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cost_usd": str(cost),
                    "fallback_used": target.fallback,
                },
            )
        return cost

    def _deadline(self, target: Target) -> float:
        return float(target.spec.get("timeout_seconds") or self.settings.default_timeout_seconds)

    # ------------------------------------------------------------------ chat

    async def chat(
        self, caller: Caller, request: ChatRequest, profile: str | None = None
    ) -> Result[ChatOutput]:
        target = await self.route(caller, profile or self.settings.default_profile)
        await self._check_budget(caller, target)
        try:
            return await self._chat_once(caller, target, request)
        except ProviderError as exc:
            fallback = target.spec.get("fallback_profile")
            if not (exc.retryable and fallback):
                raise ProviderFailed(_public_message(exc)) from exc
            log.warning("model_fallback", profile=target.name, fallback=fallback, error=str(exc))
            backup = Target(fallback, await self._profile(caller, fallback), target.requested, True)
            self._check(backup, caller.classification)
            await self._check_budget(caller, backup)
            try:
                return await self._chat_once(caller, backup, request)
            except ProviderError as exc2:
                raise ProviderFailed(_public_message(exc2)) from exc2

    def _prepare_chat(
        self, target: Target, request: ChatRequest
    ) -> tuple[ChatProvider, ChatCall, Redactor | None]:
        chat = target.spec["chat"]
        capabilities = target.spec.get("capabilities") or {}
        if request.tools and capabilities.get("tool_calling") is False:
            raise BadRequest(f"Model profile {target.name!r} does not support tool calling")
        provider = self.providers.chat(chat["provider"])
        redactor = Redactor() if target.redacts else None
        messages = (
            [_redact_message(m, redactor) for m in request.messages]
            if redactor
            else request.messages
        )
        ceiling = chat.get("max_output_tokens")
        max_tokens = request.max_tokens or ceiling or 1024
        if ceiling:
            max_tokens = min(max_tokens, int(ceiling))
        call = ChatCall(
            model=chat["model"],
            base_url=chat.get("base_url"),
            messages=messages,
            tools=request.tools,
            response_schema=request.response_schema,
            json_schema_supported=capabilities.get("json_schema_output", True),
            max_tokens=max_tokens,
            temperature=request.temperature
            if request.temperature is not None
            else chat.get("temperature"),
        )
        return provider, call, redactor

    async def chat_stream(
        self, caller: Caller, request: ChatRequest, profile: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream an answer: ``{"text": ...}`` chunks, then ``{"done": True, ...}`` with route,
        usage and cost. Same routing, floors, budgets and redaction as chat; the fallback profile is
        used only if the provider fails before the first chunk."""
        if request.tools or request.response_schema is not None:
            raise BadRequest("Streaming is for plain text answers (no tools or JSON output)")
        target = await self.route(caller, profile or self.settings.default_profile)
        await self._check_budget(caller, target)
        sent = False
        try:
            async for event in self._stream_once(caller, target, request):
                sent = sent or bool(event.get("text"))
                yield event
            return
        except ProviderError as exc:
            fallback = target.spec.get("fallback_profile")
            if sent or not (exc.retryable and fallback):
                raise ProviderFailed(_public_message(exc)) from exc
            log.warning("model_fallback", profile=target.name, fallback=fallback, error=str(exc))
            backup = Target(fallback, await self._profile(caller, fallback), target.requested, True)
            self._check(backup, caller.classification)
            await self._check_budget(caller, backup)
        try:
            async for event in self._stream_once(caller, backup, request):
                yield event
        except ProviderError as exc2:
            raise ProviderFailed(_public_message(exc2)) from exc2

    async def _stream_once(
        self, caller: Caller, target: Target, request: ChatRequest
    ) -> AsyncIterator[dict[str, Any]]:
        provider, call, redactor = self._prepare_chat(target, request)
        started = time.perf_counter()
        usage = Usage()
        pending = ""  # text held back while a redaction placeholder may still be incomplete
        deadline = self._deadline(target)
        stream = provider.chat_stream(call)
        while True:
            try:
                async with asyncio.timeout(deadline):  # deadline between chunks
                    chunk = await anext(stream)
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                raise ProviderError(
                    provider.name, f"no data within {deadline:g}s", retryable=True
                ) from exc
            if chunk.usage is not None:
                usage = chunk.usage
            if not chunk.text:
                continue
            if redactor is None:
                yield {"text": chunk.text}
                continue
            pending += chunk.text
            cut = pending.rfind("[")
            if cut != -1 and "]" not in pending[cut:]:
                ready, pending = pending[:cut], pending[cut:]
            else:
                ready, pending = pending, ""
            if ready:
                yield {"text": redactor.restore(ready)}
        if pending:
            yield {"text": redactor.restore(pending) if redactor else pending}
        model = target.spec["chat"]["model"]
        cost = await self._record(
            caller, "chat", target, provider.name, model, usage, redactor is not None, started
        )
        yield {
            "done": True,
            "usage": usage.model_dump(),
            "cost_usd": str(cost),
            "route": {
                "requested_profile": target.requested,
                "profile": target.name,
                "routed": target.name != target.requested and not target.fallback,
                "fallback_used": target.fallback,
                "provider": provider.name,
                "model": model,
                "redacted": redactor is not None,
            },
        }

    async def _chat_once(
        self, caller: Caller, target: Target, request: ChatRequest
    ) -> Result[ChatOutput]:
        chat = target.spec["chat"]
        capabilities = target.spec.get("capabilities") or {}
        if request.tools and capabilities.get("tool_calling") is False:
            raise BadRequest(f"Model profile {target.name!r} does not support tool calling")
        provider = self.providers.chat(chat["provider"])
        redactor = Redactor() if target.redacts else None
        messages = (
            [_redact_message(m, redactor) for m in request.messages]
            if redactor
            else request.messages
        )
        ceiling = chat.get("max_output_tokens")
        max_tokens = request.max_tokens or ceiling or 1024
        if ceiling:
            max_tokens = min(max_tokens, int(ceiling))
        call = ChatCall(
            model=chat["model"],
            base_url=chat.get("base_url"),
            messages=messages,
            tools=request.tools,
            response_schema=request.response_schema,
            json_schema_supported=capabilities.get("json_schema_output", True),
            max_tokens=max_tokens,
            temperature=request.temperature
            if request.temperature is not None
            else chat.get("temperature"),
        )
        started = time.perf_counter()
        output = await _with_deadline(provider.name, self._deadline(target), provider.chat(call))
        if redactor is not None:
            output = output.model_copy(
                update={
                    "content": redactor.restore(output.content)
                    if output.content
                    else output.content,
                    "tool_calls": [
                        ToolCall(
                            id=c.id, name=c.name, arguments=redactor.restore_value(c.arguments)
                        )
                        for c in output.tool_calls
                    ],
                }
            )
        cost = await self._record(
            caller,
            "chat",
            target,
            provider.name,
            chat["model"],
            output.usage,
            redactor is not None,
            started,
        )
        return Result(
            output, target, provider.name, chat["model"], output.usage, cost, redactor is not None
        )

    # ------------------------------------------------------------------ embeddings

    async def embed(
        self, caller: Caller, inputs: list[str], input_type: str, profile: str | None = None
    ) -> Result[list[list[float]]]:
        """Embeddings never route or fall back: one collection must stay in one vector space."""
        name = profile or self.settings.default_profile
        spec = await self._profile(caller, name)
        routed = _routed_to(spec, caller.classification)
        if routed is not None and routed != name:
            raise Forbidden(
                f"Model profile {name!r} routes {caller.classification} data to {routed!r}; "
                f"embed this content with {routed!r}"
            )
        target = Target(name, spec, name)
        self._check(target, caller.classification)
        await self._check_budget(caller, target)
        emb = spec["embedding"]
        provider = self.providers.embed(emb["provider"])
        redactor = Redactor() if target.redacts else None
        texts = [redactor.redact(t) for t in inputs] if redactor else inputs
        dims = int(emb["dimensions"])
        call = EmbedCall(
            model=emb["model"],
            base_url=emb.get("base_url"),
            inputs=texts,
            dimensions=dims,
            input_type="query" if input_type == "query" else "document",
        )
        started = time.perf_counter()
        try:
            output = await _with_deadline(
                provider.name, self._deadline(target), provider.embed(call)
            )
        except ProviderError as exc:
            raise ProviderFailed(_public_message(exc)) from exc
        if len(output.vectors) != len(inputs) or any(len(v) != dims for v in output.vectors):
            raise ProviderFailed(
                f"{provider.name} returned vectors that do not match {len(inputs)} x {dims}"
            )
        cost = await self._record(
            caller,
            "embed",
            target,
            provider.name,
            emb["model"],
            output.usage,
            redactor is not None,
            started,
        )
        return Result(
            output.vectors,
            target,
            provider.name,
            emb["model"],
            output.usage,
            cost,
            redactor is not None,
        )

    # ------------------------------------------------------------------ reranking

    async def rerank(
        self,
        caller: Caller,
        query: str,
        documents: list[str],
        top_n: int,
        profile: str | None = None,
    ) -> Result[list[tuple[int, float]]]:
        target = await self.route(caller, profile or self.settings.default_profile)
        reranker = target.spec.get("reranker") or {}
        if not reranker.get("enabled"):
            raise BadRequest(f"Model profile {target.name!r} has no reranker enabled")
        await self._check_budget(caller, target)
        provider = self.providers.rerank(str(reranker.get("provider")))
        redactor = Redactor() if target.redacts else None
        call = RerankCall(
            model=reranker["model"],
            base_url=reranker.get("base_url"),
            query=redactor.redact(query) if redactor else query,
            documents=[redactor.redact(d) for d in documents] if redactor else documents,
            top_n=min(top_n, len(documents)),
        )
        started = time.perf_counter()
        try:
            output = await _with_deadline(
                provider.name, self._deadline(target), provider.rerank(call)
            )
        except ProviderError as exc:
            raise ProviderFailed(_public_message(exc)) from exc
        if any(not 0 <= i < len(documents) for i, _ in output.results):
            raise ProviderFailed(f"{provider.name} returned an out-of-range document index")
        cost = await self._record(
            caller,
            "rerank",
            target,
            provider.name,
            reranker["model"],
            Usage(),
            redactor is not None,
            started,
        )
        return Result(
            output.results,
            target,
            provider.name,
            reranker["model"],
            Usage(),
            cost,
            redactor is not None,
        )

    async def aclose(self) -> None:
        await self.providers.aclose()
        await self.resolver.aclose()


def _routed_to(spec: dict[str, Any], classification: str) -> str | None:
    for rule in spec.get("routing") or []:
        if rule.get("classification") == classification:
            return str(rule["use_profile"])
    return None


def _redact_message(m: Message, redactor: Redactor | None) -> Message:
    if redactor is None:
        return m
    return m.model_copy(
        update={
            "content": redactor.redact(m.content) if m.content else m.content,
            "tool_calls": [
                ToolCall(id=c.id, name=c.name, arguments=redactor.redact_value(c.arguments))
                for c in m.tool_calls
            ]
            if m.tool_calls
            else m.tool_calls,
        }
    )


async def _with_deadline[T](provider: str, seconds: float, call: Awaitable[T]) -> T:
    try:
        async with asyncio.timeout(seconds):
            result: T = await call
            return result
    except TimeoutError as exc:
        raise ProviderError(provider, f"no response within {seconds:g}s", retryable=True) from exc


def _public_message(exc: ProviderError) -> str:
    # Provider bodies can echo request content, so for HTTP errors only the status is returned.
    if exc.status is not None:
        return f"{exc.provider} call failed (HTTP {exc.status})"
    return str(exc)
