"""Event bus port and runtime: outbox relay + consumers, run inside a service's lifespan (EV-01).

Delivery is at-least-once: the relay may publish an event twice if its commit fails after publishing
(JetStream de-duplicates by event id within a window), and consumers may see redeliveries. Consumer
handlers must therefore be idempotent (e.g. a unique event_id constraint).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.events import OutboxMixin, OutboxRelay
from nexiqon_core.settings import EventSettings

Handler = Callable[[dict[str, Any]], Awaitable[None]]
log = structlog.get_logger(__name__)
tracer = trace.get_tracer("nexiqon.events")


class Bus(Protocol):
    """Adapters: adapters/nats.py (JetStream), InMemoryBus (tests, single process)."""

    async def connect(self) -> None: ...
    async def publish(self, event: dict[str, Any]) -> None: ...
    async def subscribe(
        self, durable: str, subjects: str, handler: Handler, max_deliver: int
    ) -> None: ...
    async def close(self) -> None: ...
    def connected(self) -> bool: ...


def subject_matches(pattern: str, subject: str) -> bool:
    """NATS wildcard semantics: ``*`` one token, ``>`` one or more trailing tokens."""
    p, s = pattern.split("."), subject.split(".")
    for i, part in enumerate(p):
        if part == ">":
            return len(s) > i
        if i >= len(s) or (part != "*" and part != s[i]):
            return False
    return len(p) == len(s)


async def traced(handler: Handler, event: dict[str, Any], consumer: str) -> None:
    """Run a handler in a span that continues the producer's trace."""
    parent = (
        propagate.extract({"traceparent": event["traceparent"]})
        if event.get("traceparent")
        else None
    )
    token = otel_context.attach(parent) if parent is not None else None
    try:
        with tracer.start_as_current_span(
            f"consume {event.get('type')}",
            kind=trace.SpanKind.CONSUMER,
            attributes={
                "messaging.system": "nats",
                "messaging.consumer.group.name": consumer,
                "nexiqon.event.id": str(event.get("id")),
            },
        ):
            await handler(event)
    finally:
        if token is not None:
            otel_context.detach(token)


@dataclass
class InMemoryBus:
    """Synchronous in-process bus with the same retry and dead-letter behaviour as JetStream."""

    published: list[dict[str, Any]] = field(default_factory=list)
    dead_letters: list[dict[str, Any]] = field(default_factory=list)
    _subs: list[tuple[str, str, Handler, int]] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)
    _up: bool = False

    async def connect(self) -> None:
        self._up = True

    async def publish(self, event: dict[str, Any]) -> None:
        if event["id"] in self._seen:  # duplicate window de-duplication, like Nats-Msg-Id
            return
        self._seen.add(event["id"])
        self.published.append(event)
        for durable, subjects, handler, max_deliver in self._subs:
            if subject_matches(subjects, event["type"]):
                await self._deliver(durable, handler, event, max_deliver)

    async def _deliver(
        self, durable: str, handler: Handler, event: dict[str, Any], max_deliver: int
    ) -> None:
        for attempt in range(1, max_deliver + 1):
            try:
                await traced(handler, event, durable)
                return
            except Exception as exc:
                if attempt == max_deliver:
                    self.dead_letters.append(
                        {"consumer": durable, "error": repr(exc), "event": event}
                    )

    async def subscribe(
        self, durable: str, subjects: str, handler: Handler, max_deliver: int
    ) -> None:
        self._subs.append((durable, subjects, handler, max_deliver))

    async def close(self) -> None:
        self._up = False

    def connected(self) -> bool:
        return self._up


@dataclass
class _Consumer:
    durable: str
    subjects: str
    handler: Handler


class EventRuntime:
    """Owns a service's bus connection, outbox relay loop and consumers."""

    def __init__(self, settings: EventSettings, service: str, bus: Bus | None = None) -> None:
        self.settings = settings
        self.service = service
        if bus is None:
            from nexiqon_core.adapters.nats import JetStreamBus

            bus = JetStreamBus(settings.nats_url, settings.stream, client_name=service)
        self.bus = bus
        self._relays: list[tuple[TenantSessionFactory, type[OutboxMixin]]] = []
        self._subs: list[_Consumer] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._stop = asyncio.Event()

    def relay(self, sessions: TenantSessionFactory, model: type[OutboxMixin]) -> None:
        self._relays.append((sessions, model))

    def subscribe(self, durable: str, subjects: str, handler: Handler) -> None:
        self._subs.append(_Consumer(durable, subjects, handler))

    async def relay_once(self) -> int:
        total = 0
        for sessions, model in self._relays:
            async with sessions.system_session() as s:
                total += await OutboxRelay(self.bus, model).relay_once(s)
        return total

    async def _relay_loop(self) -> None:
        interval = self.settings.relay_interval_ms / 1000
        backoff = interval
        while not self._stop.is_set():
            try:
                published = await self.relay_once()
                backoff = interval
            except Exception:
                log.exception("outbox_relay_failed", service=self.service)
                published, backoff = 0, min(backoff * 2, 30.0)
            if published == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)

    async def start(self) -> None:
        self._stop.clear()
        await self.bus.connect()
        for sub in self._subs:
            await self.bus.subscribe(
                sub.durable, sub.subjects, sub.handler, self.settings.max_deliver
            )
        if self._relays:
            self._tasks.append(
                asyncio.create_task(self._relay_loop(), name=f"{self.service}-relay")
            )

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        await self.bus.close()

    async def ready(self) -> bool:
        return self.bus.connected()


def encode(event: dict[str, Any]) -> bytes:
    return json.dumps(event, separators=(",", ":")).encode()


__all__ = ["Bus", "EventRuntime", "Handler", "InMemoryBus", "encode", "subject_matches", "traced"]
