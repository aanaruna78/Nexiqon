"""Structured JSON logging with request, trace and tenant correlation."""

from __future__ import annotations

import logging
import re
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


# PII and secrets never reach logs (S-02). Keys are matched by name; values by shape.
SECRET_KEYS = re.compile(
    r"(pass(word)?|secret|token|authorization|api[_-]?key|cookie|private[_-]?key|credential)",
    re.IGNORECASE,
)
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"), "[jwt]"),
    (re.compile(r"\b(nxq|whsec|sk|pk)_[A-Za-z0-9_-]{12,}"), "[key]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{12,}=*"), "Bearer [redacted]"),
    (re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(\.[\w-]{1,63})+"), "[email]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[number]"),
    (re.compile(r"\+?\(?\d{1,4}\)?[ .-]?\d{2,4}[ .-]\d{3,4}[ .-]?\d{3,4}\b"), "[phone]"),
]
KEEP = frozenset(
    {
        "event",
        "timestamp",
        "level",
        "tenant_id",
        "actor_id",
        "trace_id",
        "span_id",
        "request_id",
        "service",
        "logger",
    }
)


def redact_text(value: str) -> str:
    for pattern, replacement in PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _redact_value(key: str, value: Any, depth: int = 0) -> Any:
    if SECRET_KEYS.search(key):
        return "[redacted]"
    if isinstance(value, str):
        return redact_text(value)
    if depth < 3 and isinstance(value, dict):
        return {k: _redact_value(str(k), v, depth + 1) for k, v in value.items()}
    if depth < 3 and isinstance(value, list | tuple):
        return [_redact_value(key, v, depth + 1) for v in value]
    return value


def redact(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Mask secrets (by key) and personal data (emails, phone and card numbers, tokens)."""
    for key in list(event):
        if key not in KEEP:
            event[key] = _redact_value(key, event[key])
    if isinstance(event.get("event"), str):
        event["event"] = redact_text(event["event"])
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
            redact,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )
    # The service name is bound per request (app middleware), not per process: in a deployment
    # group several services share one process.
