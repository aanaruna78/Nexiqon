"""One trace across HTTP, a service-to-service call and an event consumer; per-tenant flags."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI
from openfeature.provider.in_memory_provider import InMemoryFlag
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from nexiqon_core.bus import InMemoryBus
from nexiqon_core.events import current_traceparent
from nexiqon_core.flags import Flags
from nexiqon_core.settings import FlagSettings, TelemetrySettings
from nexiqon_core.telemetry import configure_providers
from nexiqon_core.testing import TwoTenants

EXPORTER = InMemorySpanExporter()


async def test_trace_spans_http_service_call_and_event() -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    configure_providers("test", "0", TelemetrySettings(enabled=True), exporter=EXPORTER)
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))

    bus = InMemoryBus()
    consumed: list[str] = []

    async def consumer(e: dict[str, Any]) -> None:
        consumed.append(trace.get_current_span().get_span_context().trace_id.__format__("032x"))

    await bus.subscribe("audit", "nexiqon.>", consumer, 3)

    b = FastAPI()

    @b.get("/b")
    async def b_route() -> dict[str, str]:
        return {"ok": "b"}

    FastAPIInstrumentor.instrument_app(b)
    a = FastAPI()
    router = APIRouter()

    @router.get("/a")
    async def a_route() -> dict[str, str | None]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=b), base_url="http://b"
        ) as client:
            await client.get("/b")
        await bus.publish(
            {
                "id": str(uuid.uuid4()),
                "type": "nexiqon.test.thing.done",
                "source": "a",
                "traceparent": current_traceparent(),
                "data": {},
            }
        )
        return {"traceparent": current_traceparent()}

    a.include_router(router)
    FastAPIInstrumentor.instrument_app(a)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=a), base_url="http://a"
    ) as client:
        traceparent = (await client.get("/a")).json()["traceparent"]

    trace_id = traceparent.split("-")[1]
    spans = [
        s for s in EXPORTER.get_finished_spans() if format(s.context.trace_id, "032x") == trace_id
    ]
    names = {s.name for s in spans}
    assert any("GET /a" in n for n in names)
    assert any("GET /b" in n for n in names)  # downstream service joined the trace
    assert "consume nexiqon.test.thing.done" in names
    assert consumed == [trace_id]


def test_flags_are_evaluated_per_tenant() -> None:
    t = TwoTenants.create()
    a = str(t.a.context.tenant_id)

    def only_tenant_a(flag: InMemoryFlag[Any], ctx: Any) -> Any:
        from openfeature.flag_evaluation import FlagResolutionDetails

        on = ctx is not None and ctx.targeting_key == a
        return FlagResolutionDetails(value=on, variant="on" if on else "off")

    flags = Flags(
        FlagSettings(provider="in_memory"),
        service="flags-test",
        in_memory={
            "answer-inspector": InMemoryFlag(
                "off", {"on": True, "off": False}, context_evaluator=only_tenant_a
            ),
            "theme": InMemoryFlag("teal", {"teal": "teal"}),
        },
    )
    assert flags.enabled("answer-inspector", t.a.context) is True
    assert flags.enabled("answer-inspector", t.b.context) is False
    assert flags.enabled("unknown-flag", t.a.context, default=True) is True
    assert flags.string("theme", None, "x") == "teal"
