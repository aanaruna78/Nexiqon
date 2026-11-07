"""Event bus semantics: wildcards, de-duplication, retries and dead letters (in-memory + JetStream)."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from nexiqon_core.bus import InMemoryBus, subject_matches


def event(type_: str = "nexiqon.identity.tenant.created", **extra: Any) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "type": type_,
        "source": "test",
        "time": "2026-11-07T10:00:00+00:00",
        "nexiqontenantid": str(uuid.uuid4()),
        "nexiqonactorid": "u",
        "data": {},
        **extra,
    }


@pytest.mark.parametrize(
    ("pattern", "subject", "ok"),
    [
        ("nexiqon.>", "nexiqon.identity.tenant.created", True),
        ("nexiqon.identity.>", "nexiqon.config.x.y", False),
        ("nexiqon.*.tenant.created", "nexiqon.identity.tenant.created", True),
        ("nexiqon.*.tenant", "nexiqon.identity.tenant.created", False),
        ("nexiqon.>", "nexiqon", False),
    ],
)
def test_subject_matching(pattern: str, subject: str, ok: bool) -> None:
    assert subject_matches(pattern, subject) is ok


async def test_dedupe_retry_and_dead_letter() -> None:
    bus = InMemoryBus()
    seen: list[str] = []
    attempts = {"n": 0}

    async def ok(e: dict[str, Any]) -> None:
        seen.append(e["id"])

    async def flaky(e: dict[str, Any]) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")

    async def broken(e: dict[str, Any]) -> None:
        raise RuntimeError("poison")

    await bus.subscribe("ok", "nexiqon.>", ok, 5)
    await bus.subscribe("flaky", "nexiqon.identity.>", flaky, 5)
    await bus.subscribe("broken", "nexiqon.identity.>", broken, 3)
    e = event()
    await bus.publish(e)
    await bus.publish(e)  # duplicate id: dropped
    assert seen == [e["id"]]
    assert attempts["n"] == 3
    assert [d["consumer"] for d in bus.dead_letters] == ["broken"]


@pytest.fixture(scope="module")
def nats_url() -> Iterator[str]:
    if shutil.which("docker") is None:
        pytest.skip("Docker not available")
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    container = DockerContainer("nats:2.15.1-alpine").with_command("-js").with_exposed_ports(4222)
    with container:
        wait_for_logs(container, "Server is ready", timeout=30)
        yield f"nats://{container.get_container_host_ip()}:{container.get_exposed_port(4222)}"


@pytest.mark.integration
async def test_jetstream_delivery_dedupe_and_dlq(nats_url: str) -> None:
    from nexiqon_core.adapters.nats import JetStreamBus

    received: list[str] = []
    calls = {"poison": 0}
    done = asyncio.Event()

    async def handler(e: dict[str, Any]) -> None:
        received.append(e["id"])
        if len(received) >= 2:
            done.set()

    async def poison(e: dict[str, Any]) -> None:
        calls["poison"] += 1
        raise RuntimeError("cannot process")

    bus = JetStreamBus(nats_url, "TEST_EVENTS", client_name="test")
    await bus.connect()
    await bus.subscribe("audit-test", "nexiqon.>", handler, 3)
    await bus.subscribe("poison-test", "nexiqon.config.>", poison, 2)
    first, second = event(), event("nexiqon.config.version.published")
    await bus.publish(first)
    await bus.publish(first)  # same Nats-Msg-Id: stored once
    await bus.publish(second)
    await asyncio.wait_for(done.wait(), timeout=15)
    for _ in range(100):  # poison: delivered max_deliver times then dead-lettered
        if calls["poison"] >= 2:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.5)
    assert sorted(received) == sorted([first["id"], second["id"]])
    assert calls["poison"] == 2
    assert bus._js is not None
    dlq = await bus._js.pull_subscribe("dlq.poison-test", durable="dlq-reader")
    msgs = await dlq.fetch(1, timeout=5)
    assert b"cannot process" in msgs[0].data
    await bus.close()

    # A durable consumer resumes after a restart without redelivering acknowledged events.
    restarted = JetStreamBus(nats_url, "TEST_EVENTS", client_name="test-2")
    again: list[str] = []

    async def collect(e: dict[str, Any]) -> None:
        again.append(e["id"])

    await restarted.connect()
    await restarted.subscribe("audit-test", "nexiqon.>", collect, 3)
    third = event()
    await restarted.publish(third)
    for _ in range(50):
        if again:
            break
        await asyncio.sleep(0.1)
    assert again == [third["id"]]
    await restarted.close()
