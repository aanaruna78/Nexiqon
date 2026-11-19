"""Platform events to webhooks and the in-app inbox (NT-01).

Webhooks: every event a tenant's webhook subscribes to becomes a delivery, sent as the CloudEvent
JSON with ``X-Nexiqon-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>``. Sending
goes through the SSRF-safe fetcher (public HTTPS only by default) without following redirects.
Failures retry with backoff; after ``max_attempts`` the delivery gives up, and a webhook that keeps
failing is switched off.

Inbox: a few events are worth a person's attention in Studio; each becomes an item for the roles
that act on it. Items carry ids and numbers, never content (questions, answers).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.fetch import SafeFetcher
from nexiqon_core.tenancy import TenantContext
from nexiqon_notification.models import InboxItem, Webhook, WebhookDelivery

log = structlog.get_logger(__name__)
BACKOFF = [30, 120, 600, 1800, 7200]  # seconds before attempts 2..6
DISABLE_AFTER = 20  # consecutive failed deliveries switch a webhook off


def sign(secret: str, body: bytes, at: int | None = None) -> str:
    t = int(time.time()) if at is None else at
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def matches(patterns: list[str], event_type: str) -> bool:
    """``conversation.escalated`` (exact) or ``evaluation.*`` (prefix); none means all."""
    short = event_type.removeprefix("nexiqon.")
    if not patterns:
        return True
    for p in patterns:
        if p.endswith(".*") and short.startswith(p[:-1]):
            return True
        if p == short:
            return True
    return False


def inbox_item(event: dict[str, Any]) -> dict[str, Any] | None:
    """The in-app notification an event deserves, if any: kind, roles, params, link."""
    short = str(event.get("type", "")).removeprefix("nexiqon.")
    d: dict[str, Any] = event.get("data") or {}
    if short == "metering.budget.threshold_reached":
        return {
            "kind": "budget",
            "roles": ["owner", "admin"],
            "params": {k: d.get(k) for k in ("agent", "threshold", "spent_usd", "limit_usd")},
            "link": "/insights",
        }
    if short == "conversation.escalated":
        return {
            "kind": "handover",
            "roles": ["owner", "admin", "editor", "member"],
            "params": {"agent": d.get("agent")},
            "link": f"/conversations?c={d.get('conversation_id')}",
        }
    if short in ("evaluation.run.completed", "evaluation.run.failed"):
        return {
            "kind": "evaluation_" + short.rsplit(".", 1)[-1],
            "roles": ["owner", "admin", "editor"],
            "params": {k: d.get(k) for k in ("agent", "version", "pass_rate")},
            "link": f"/evaluations/{d.get('test_set_id')}?run={d.get('run_id')}",
        }
    if short.startswith("governance.tenant.") and short.rsplit(".", 1)[-1] in (
        "requested",
        "completed",
        "failed",
        "cancelled",
    ):
        _, _, kind, outcome = short.split(".")
        return {
            "kind": f"{kind}_{outcome}",
            "roles": ["owner"],
            "params": {"run_after": d.get("run_after")},
            "link": "/settings/organization?tab=data",
        }
    if short == "governance.retention.completed" and d.get("errors"):
        return {
            "kind": "retention_errors",
            "roles": ["owner", "admin"],
            "params": {"services": d.get("errors")},
            "link": "/settings/organization?tab=data",
        }
    return None


class Dispatcher:
    def __init__(
        self, db: TenantSessionFactory, fetcher: SafeFetcher, max_attempts: int = 6
    ) -> None:
        self.db = db
        self.fetcher = fetcher
        self.max_attempts = max_attempts

    async def __call__(self, event: dict[str, Any]) -> None:
        """Consumer of every event: record deliveries and inbox items (idempotent)."""
        kind = str(event.get("type", ""))
        if kind.startswith("nexiqon.notification."):
            return  # never notify about notifications
        tenant = uuid.UUID(str(event["nexiqontenantid"]))
        event_id = uuid.UUID(str(event["id"]))
        ctx = TenantContext(tenant_id=tenant, actor_id="service:notification", actor_type="service")
        async with self.db.session(ctx) as s:
            hooks = list(await s.scalars(select(Webhook).where(Webhook.enabled.is_(True))))
            for hook in hooks:
                if not matches(list(hook.events or []), kind):
                    continue
                await s.execute(
                    insert(WebhookDelivery)
                    .values(
                        id=uuid.uuid4(),
                        tenant_id=tenant,
                        webhook_id=hook.id,
                        event_id=event_id,
                        event_type=kind,
                        payload=event,
                        status="pending",
                        attempts=0,
                        next_attempt_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing(index_elements=["webhook_id", "event_id"])
                )
            item = inbox_item(event)
            if item is not None:
                exists = await s.scalar(select(InboxItem.id).where(InboxItem.event_id == event_id))
                if exists is None:
                    s.add(InboxItem(tenant_id=tenant, event_id=event_id, **item))
        await self.send_due(tenant)

    async def send_due(self, tenant: uuid.UUID | None = None) -> int:
        """Attempt every delivery that is due (one tenant, or all from the retry loop)."""
        sent = 0
        async with self.db.scoped({"webhook_sweep": "on"}) as s:
            q = select(WebhookDelivery.tenant_id, WebhookDelivery.id).where(
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_attempt_at <= datetime.now(UTC),
            )
            if tenant is not None:
                q = q.where(WebhookDelivery.tenant_id == tenant)
            due = (await s.execute(q.limit(200))).all()
        for tenant_id, delivery_id in due:
            sent += int(await self.attempt(tenant_id, delivery_id))
        return sent

    async def attempt(self, tenant: uuid.UUID, delivery_id: uuid.UUID) -> bool:
        ctx = TenantContext(tenant_id=tenant, actor_id="service:notification", actor_type="service")
        async with self.db.session(ctx) as s:
            d = await s.get(WebhookDelivery, delivery_id)
            if d is None or d.status != "pending":
                return False
            hook = await s.get(Webhook, d.webhook_id)
            if hook is None or not hook.enabled:
                d.status, d.error = "failed", "webhook removed or switched off"
                return False
            url, secret, payload = hook.url, hook.secret, d.payload
        body = json.dumps(payload, separators=(",", ":"), default=str).encode()
        status: int | None = None
        error: str | None = None
        try:
            result = await self.fetcher.request(
                "POST",
                url,
                headers={
                    "content-type": "application/cloudevents+json",
                    "x-nexiqon-signature": sign(secret, body),
                    "x-nexiqon-event": str(payload.get("type", "")),
                    "x-nexiqon-delivery": str(delivery_id),
                },
                content=body,
            )
            status = result.status
            if not 200 <= status < 300:
                error = f"answered {status}"
        except Exception as exc:  # unreachable, blocked address, timeout
            error = f"{type(exc).__name__}: {exc}"[:500]
        async with self.db.session(ctx) as s:
            d = await s.get(WebhookDelivery, delivery_id)
            hook = await s.get(Webhook, d.webhook_id) if d else None
            if d is None or hook is None:
                return False
            d.attempts += 1
            d.response_status, d.error = status, error
            if error is None:
                d.status, d.next_attempt_at = "delivered", None
                hook.failures = 0
                return True
            hook.failures += 1
            if hook.failures >= DISABLE_AFTER:
                hook.enabled = False
            if d.attempts >= self.max_attempts:
                d.status, d.next_attempt_at = "failed", None
            else:
                wait = BACKOFF[min(d.attempts - 1, len(BACKOFF) - 1)]
                d.next_attempt_at = datetime.now(UTC) + timedelta(seconds=wait)
            log.info("webhook_failed", delivery=str(delivery_id), attempt=d.attempts, error=error)
            return False
