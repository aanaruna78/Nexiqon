"""OpenTelemetry setup. Exports OTLP/HTTP to any backend (Grafana LGTM by default)."""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from nexiqon_core.settings import TelemetrySettings

_configured = False


def configure_telemetry(app: FastAPI, service: str, version: str, cfg: TelemetrySettings) -> None:
    """Instrument ``app``; installs a global tracer provider once per process."""
    global _configured
    if not cfg.enabled:
        return
    if not _configured:
        provider = TracerProvider(
            resource=Resource.create({"service.name": service, "service.version": version})
        )
        if cfg.otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=f"{cfg.otlp_endpoint.rstrip('/')}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _configured = True
    FastAPIInstrumentor.instrument_app(app)
