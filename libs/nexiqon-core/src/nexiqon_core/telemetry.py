"""OpenTelemetry: traces and metrics over OTLP/HTTP to any backend (Grafana LGTM by default).

Trace context crosses every boundary (OB-01):
* inbound HTTP (FastAPI instrumentation) and outbound HTTP (httpx: authz, snapshots, tools);
* events: the producer's ``traceparent`` is stored with the outbox row and continued by consumers
  (see nexiqon_core.bus.traced);
* the edge gateway (Envoy) starts the trace and sends the ``traceparent`` header.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from nexiqon_core.settings import TelemetrySettings

_configured = False


def configure_providers(
    service: str, version: str, cfg: TelemetrySettings, exporter: SpanExporter | None = None
) -> None:
    """Install global tracer/meter providers once per process (a deployment group shares them)."""
    global _configured
    if _configured:
        return
    # In a deployment group several services share a process: the resource is the group, and each
    # span carries nexiqon.service (see configure_telemetry).
    group = os.environ.get("NEXIQON_DEPLOYMENT_GROUP")
    resource = Resource.create(
        {
            "service.name": group or service,
            "service.version": version,
            "nexiqon.deployment_group": group or service,
        }
    )
    provider = TracerProvider(resource=resource)
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    elif cfg.otlp_endpoint:
        endpoint = cfg.otlp_endpoint.rstrip("/")
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"), export_interval_millis=15_000
        )
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    _configured = True


def configure_telemetry(app: FastAPI, service: str, version: str, cfg: TelemetrySettings) -> None:
    """Instrument ``app`` (each service in a group is instrumented, sharing the providers)."""
    if not cfg.enabled:
        return
    configure_providers(service, version, cfg)

    def tag(span: Any, _scope: dict[str, Any]) -> None:
        if span is not None and span.is_recording():
            span.set_attribute("nexiqon.service", service)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz", server_request_hook=tag)
