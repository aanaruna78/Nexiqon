"""Structured JSON logging with request, trace and tenant correlation."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from nexiqon_core.tenancy import current_context


def _add_tenant(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    ctx = current_context()
    if ctx is not None:
        event.setdefault("tenant_id", str(ctx.tenant_id))
        event.setdefault("actor_id", ctx.actor_id)
    return event


def _add_trace(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    from opentelemetry import trace

    span = trace.get_current_span().get_span_context()
    if span.is_valid:
        event.setdefault("trace_id", format(span.trace_id, "032x"))
        event.setdefault("span_id", format(span.span_id, "016x"))
    return event


def configure_logging(service: str, level: str = "INFO", json: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_tenant,
            _add_trace,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.bind_contextvars(service=service)
