"""Clerk webhooks (Svix-signed): organisations become tenants, org memberships become memberships."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from nexiqon_core.db import TenantSessionFactory, set_variables
from nexiqon_core.errors import BadRequest, Unauthorized
from nexiqon_core.events import add_event
from nexiqon_core.ids import uuid7
from nexiqon_identity.access import SOURCE, system_context
from nexiqon_identity.models import Membership, Outbox, Tenant, User
from nexiqon_identity.settings import IdpProviderSettings

TOLERANCE_SECONDS = 300
CLERK_ROLE_MAP = {"org:admin": "admin", "org:member": "member"}


def verify_svix(
    secret: str, headers: Mapping[str, str], body: bytes, now: float | None = None
) -> None:
    msg_id = headers.get("svix-id")
    timestamp = headers.get("svix-timestamp")
    signatures = headers.get("svix-signature")
    if not (msg_id and timestamp and signatures):
        raise Unauthorized("Missing webhook signature")
    try:
        sent = int(timestamp)
    except ValueError as exc:
        raise Unauthorized("Bad webhook timestamp") from exc
    if abs((now if now is not None else time.time()) - sent) > TOLERANCE_SECONDS:
        raise Unauthorized("Webhook timestamp outside tolerance")
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in signatures.split():
        version, _, sig = part.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return
    raise Unauthorized("Invalid webhook signature")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return (slug or "tenant")[:50]


class ClerkWebhooks:
    def __init__(self, db: TenantSessionFactory, provider: IdpProviderSettings) -> None:
        self.db = db
        self.provider = provider

    async def handle(self, event: dict[str, Any]) -> str:
        kind = event.get("type")
        data = event.get("data") or {}
        if not isinstance(data, dict):
            raise BadRequest("Malformed webhook")
        if kind in ("organization.created", "organization.updated"):
            await self._upsert_org(data)
        elif kind == "organization.deleted":
            await self._suspend_org(str(data.get("id", "")))
        elif kind in ("organizationMembership.created", "organizationMembership.updated"):
            await self._upsert_membership(data)
        elif kind == "organizationMembership.deleted":
            await self._remove_membership(data)
        else:
            return "ignored"
        return "processed"

    async def _tenant_for_org(self, s: Any, org_id: str) -> Tenant | None:
        await set_variables(s, idp_provider=self.provider.name, idp_org_ref=org_id)
        tenant: Tenant | None = await s.scalar(
            select(Tenant).where(
                Tenant.idp_provider == self.provider.name, Tenant.idp_org_ref == org_id
            )
        )
        if tenant is not None:
            await set_variables(s, tenant_id=str(tenant.id))
        return tenant

    async def _upsert_org(self, data: dict[str, Any]) -> None:
        org_id = str(data["id"])
        async with self.db.scoped({}) as s:
            tenant = await self._tenant_for_org(s, org_id)
            if tenant is None:
                tenant_id = uuid7()
                await set_variables(s, tenant_id=str(tenant_id))
                slug = _slugify(str(data.get("slug") or data.get("name") or org_id))
                tenant = Tenant(
                    id=tenant_id,
                    slug=f"{slug}-{str(tenant_id)[-6:]}",
                    name=str(data.get("name") or slug),
                    idp_provider=self.provider.name,
                    idp_org_ref=org_id,
                )
                s.add(tenant)
                await s.flush()
                add_event(
                    s,
                    Outbox,
                    system_context(tenant.id, "clerk-webhook"),
                    source=SOURCE,
                    type="nexiqon.identity.tenant.created",
                    subject=str(tenant.id),
                    data={"slug": tenant.slug, "via": "clerk"},
                )
            elif data.get("name"):
                tenant.name = str(data["name"])

    async def _suspend_org(self, org_id: str) -> None:
        async with self.db.scoped({}) as s:
            tenant = await self._tenant_for_org(s, org_id)
            if tenant is not None:
                tenant.status = "suspended"
                add_event(
                    s,
                    Outbox,
                    system_context(tenant.id, "clerk-webhook"),
                    source=SOURCE,
                    type="nexiqon.identity.tenant.suspended",
                    subject=str(tenant.id),
                    data={"via": "clerk"},
                )

    async def _upsert_membership(self, data: dict[str, Any]) -> None:
        org = data.get("organization") or {}
        user_data = data.get("public_user_data") or {}
        org_id, subject = str(org.get("id", "")), str(user_data.get("user_id", ""))
        if not org_id or not subject:
            raise BadRequest("Membership event without organization or user")
        if org.get("id"):
            await self._upsert_org(org)  # tolerate out-of-order delivery
        role = CLERK_ROLE_MAP.get(str(data.get("role")), "member")
        issuer = self.provider.issuer.rstrip("/")
        async with self.db.scoped({"idp_issuer": issuer, "idp_subject": subject}) as s:
            user = await s.scalar(
                select(User).where(User.idp_issuer == issuer, User.idp_subject == subject)
            )
            if user is None:
                identifier = user_data.get("identifier")
                user = User(
                    idp_issuer=issuer,
                    idp_subject=subject,
                    email=str(identifier).lower() if identifier else None,
                    display_name=" ".join(
                        str(user_data.get(k))
                        for k in ("first_name", "last_name")
                        if user_data.get(k)
                    )
                    or None,
                )
                s.add(user)
                await s.flush()
            tenant = await self._tenant_for_org(s, org_id)
            assert tenant is not None
            membership = await s.scalar(
                select(Membership).where(
                    Membership.tenant_id == tenant.id, Membership.user_id == user.id
                )
            )
            has_owner = await s.scalar(
                select(Membership.id).where(
                    Membership.tenant_id == tenant.id, Membership.role == "owner"
                )
            )
            if membership is None:
                membership = Membership(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role="owner" if (has_owner is None and role == "admin") else role,
                    status="active",
                    invited_by="clerk",
                )
                s.add(membership)
            elif membership.role != "owner":
                membership.role = role
            await s.flush()
            add_event(
                s,
                Outbox,
                system_context(tenant.id, "clerk-webhook"),
                source=SOURCE,
                type="nexiqon.identity.membership.synced",
                subject=str(membership.id),
                data={"role": membership.role, "via": "clerk"},
            )

    async def _remove_membership(self, data: dict[str, Any]) -> None:
        org_id = str((data.get("organization") or {}).get("id", ""))
        subject = str((data.get("public_user_data") or {}).get("user_id", ""))
        issuer = self.provider.issuer.rstrip("/")
        async with self.db.scoped({"idp_issuer": issuer, "idp_subject": subject}) as s:
            user = await s.scalar(
                select(User).where(User.idp_issuer == issuer, User.idp_subject == subject)
            )
            tenant = await self._tenant_for_org(s, org_id)
            if user is None or tenant is None:
                return
            membership = await s.scalar(
                select(Membership).where(
                    Membership.tenant_id == tenant.id, Membership.user_id == user.id
                )
            )
            if membership is not None:
                membership.status = "disabled"
                add_event(
                    s,
                    Outbox,
                    system_context(tenant.id, "clerk-webhook"),
                    source=SOURCE,
                    type="nexiqon.identity.membership.disabled",
                    subject=str(membership.id),
                    data={"via": "clerk"},
                )
