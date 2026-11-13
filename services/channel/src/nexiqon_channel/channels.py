"""Channel plugin port (CH-01). A channel turns a resolved agent into what a client needs to
talk to it: presentation for the web widget, endpoints for API callers. Slack, Teams and email
plug in here later without touching the conversation or agent services.

Every channel uses the same conversation endpoints, so streaming (server-sent events with
status, sources, tool progress and answer text), citations, approvals and handoff work the same
everywhere.
"""

from __future__ import annotations

from typing import Any, Protocol

ENDPOINTS = {
    "start": "/conversation/v1/conversations",
    "send": "/conversation/v1/conversations/{id}/messages",
    "stream": "/conversation/v1/conversations/{id}/messages/stream",
    "approve": "/conversation/v1/conversations/{id}/approval",
    "handoff": "/conversation/v1/conversations/{id}/handoff",
    "history": "/conversation/v1/conversations/{id}",
    "feedback": "/conversation/v1/messages/{id}/feedback",
}
STREAM_EVENTS = ["run", "status", "sources", "tool", "delta", "message", "error"]


def _text(value: Any, locale: str) -> str | None:
    if isinstance(value, dict):
        return value.get(locale) or value.get("en") or next(iter(value.values()), None)
    return str(value) if value else None


class Channel(Protocol):
    name: str
    description: str

    def settings(self, resolved: dict[str, Any], locale: str) -> dict[str, Any]: ...


class ApiChannel:
    name = "api"
    description = "Server-to-server: an API key calls the conversation endpoints directly."

    def settings(self, resolved: dict[str, Any], locale: str) -> dict[str, Any]:
        return {
            "channel": self.name,
            "agent": resolved["agent"],
            "endpoints": ENDPOINTS,
            "stream_events": STREAM_EVENTS,
        }


class WidgetChannel:
    name = "widget"
    description = "The embeddable web widget: a widget key, allowed origins, one id per visitor."

    def settings(self, resolved: dict[str, Any], locale: str) -> dict[str, Any]:
        config = resolved.get("config") or {}
        pack = resolved.get("pack") or {}
        widget = (pack.get("channels") or {}).get("widget") or {}
        name = str(config.get("display_name") or _text(widget.get("title"), locale) or "Assistant")
        starters = widget.get("starter_questions") or {}
        escalation = config.get("escalation") or {}
        return {
            "channel": self.name,
            "agent": resolved["agent"],
            "locale": locale,
            "title": _text(widget.get("title"), locale) or name,
            "assistant_name": name,
            "greeting": _text(widget.get("greeting"), locale),
            "starter_questions": list(starters.get(locale) or starters.get("en") or [])[:6],
            "accent_color": widget.get("accent_color"),
            "handoff": escalation.get("on_user_request", True),
            "endpoints": ENDPOINTS,
            "stream_events": STREAM_EVENTS,
        }


REGISTRY: dict[str, Channel] = {c.name: c for c in (WidgetChannel(), ApiChannel())}
