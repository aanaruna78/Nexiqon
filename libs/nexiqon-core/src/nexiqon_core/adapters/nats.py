"""NATS JetStream adapter for the event bus port (ADR 0006)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import nats
import structlog
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, RetentionPolicy, StreamConfig
from nats.js.errors import NotFoundError

from nexiqon_core.bus import Handler, encode, traced

log = structlog.get_logger(__name__)
DLQ_STREAM = "NEXIQON_DLQ"


class JetStreamBus:
    def __init__(self, url: str, stream: str, *, client_name: str = "nexiqon") -> None:
        self._url = url
        self._stream = stream
        self._name = client_name
        self._nc: Client | None = None
        self._js: JetStreamContext | None = None
        self._tasks: list[asyncio.Task[None]] = []

    async def connect(self) -> None:
        self._nc = await nats.connect(
            self._url, name=self._name, max_reconnect_attempts=-1, reconnect_time_wait=1
        )
        self._js = self._nc.jetstream()
        await self._ensure_stream(self._stream, ["nexiqon.>"])
        await self._ensure_stream(DLQ_STREAM, ["dlq.>"])

    async def _ensure_stream(self, name: str, subjects: list[str]) -> None:
        assert self._js is not None
        try:
            await self._js.stream_info(name)
        except NotFoundError:
            await self._js.add_stream(
                StreamConfig(
                    name=name,
                    subjects=subjects,
                    retention=RetentionPolicy.LIMITS,
                    max_age=7 * 24 * 3600,
                    duplicate_window=120,
                )
            )

    async def publish(self, event: dict[str, Any]) -> None:
        assert self._js is not None, "not connected"
        await self._js.publish(
            event["type"],
            encode(event),
            headers={
                "Nats-Msg-Id": str(event["id"]),
                "Content-Type": "application/cloudevents+json",
            },
        )

    async def subscribe(
        self, durable: str, subjects: str, handler: Handler, max_deliver: int
    ) -> None:
        assert self._js is not None, "not connected"
        sub = await self._js.pull_subscribe(
            subjects,
            durable=durable,
            config=ConsumerConfig(
                ack_policy=AckPolicy.EXPLICIT, max_deliver=max_deliver + 1, ack_wait=30
            ),
        )
        self._tasks.append(asyncio.create_task(self._pull(sub, durable, handler, max_deliver)))

    async def _pull(
        self,
        sub: JetStreamContext.PullSubscription,
        durable: str,
        handler: Handler,
        max_deliver: int,
    ) -> None:
        while True:
            try:
                messages = await sub.fetch(batch=50, timeout=1)
            except TimeoutError:
                continue
            except Exception:
                log.exception("consumer_fetch_failed", consumer=durable)
                await asyncio.sleep(1)
                continue
            for msg in messages:
                await self._handle(msg, durable, handler, max_deliver)

    async def _handle(self, msg: Msg, durable: str, handler: Handler, max_deliver: int) -> None:
        event = json.loads(msg.data)
        try:
            await traced(handler, event, durable)
            await msg.ack()
        except Exception as exc:
            attempts = msg.metadata.num_delivered
            if attempts >= max_deliver:
                log.error(
                    "event_dead_lettered",
                    consumer=durable,
                    event_id=event.get("id"),
                    error=repr(exc),
                )
                assert self._js is not None
                await self._js.publish(
                    f"dlq.{durable}",
                    json.dumps({"consumer": durable, "error": repr(exc), "event": event}).encode(),
                )
                await msg.ack()
            else:
                await msg.nak(delay=min(2**attempts, 30))

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        if self._nc is not None and not self._nc.is_closed:
            await self._nc.drain()
        self._nc = self._js = None

    def connected(self) -> bool:
        return self._nc is not None and self._nc.is_connected
