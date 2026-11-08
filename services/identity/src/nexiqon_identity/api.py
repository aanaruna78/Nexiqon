"""HTTP API for identity. Contract: contracts/openapi/identity.json."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import AwareDatetime, BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexiqon_core.authz import Resource, require_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import BadRequest, Conflict, Forbidden, NotFound, Unauthorized
from nexiqon_core.events import add_event
from nexiqon_core.ids import uuid7
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext, require_current_context
from nexiqon_identity import apikeys, keys
from nexiqon_identity.access import SOURCE, AccessService
from nexiqon_identity.models import (
    KEY_ROLES,
    ApiKey,
    Group,
    GroupMember,
    Membership,
    Outbox,
    Tenant,
    User,
)
from nexiqon_identity.webhooks import ClerkWebhooks, verify_svix

TENANT_HEADER = "X-Nexiqon-Tenant"
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")

public_router = APIRouter(tags=["identity"])
tenant_router = APIRouter(prefix="/v1", tags=["identity"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]


def _access(request: Request) -> AccessService:
    service: AccessService | None = request.app.state.access
    if service is None:
        raise Unauthorized("Identity service is not configured")
    return service


def _db(request: Request) -> TenantSessionFactory:
    db: TenantSessionFactory | None = request.app.state.db
    if db is None:
        raise Unauthorized("Identity database is not configured")
    return db


def _event(
    s: AsyncSession, ctx: TenantContext, type_: str, subject: uuid.UUID, **data: Any
) -> None:
    add_event(
        s,
        Outbox,
        ctx,
        source=SOURCE,
        type=f"nexiqon.identity.{type_}",
        subject=str(subject),
        data=data,
    )


# ======================================================================= public / gateway


@public_router.get("/.well-known/jwks.json", include_in_schema=False)
async def jwks(request: Request) -> dict[str, Any]:
    """Public keys for tenant-context tokens (services may fetch instead of static config)."""
    return keys.jwks(request.app.state.settings.signing)


@public_router.api_route(
    "/internal/ext-authz/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def ext_authz(
    request: Request,
    path: str,
    authorization: Annotated[str | None, Header()] = None,
    tenant: Annotated[str | None, Header(alias=TENANT_HEADER)] = None,
    origin: Annotated[str | None, Header()] = None,
) -> Response:
    """Envoy ext_authz check: 200 + X-Nexiqon-Context, or 401/403. Not routed by the gateway."""
    token = await _access(request).context_for(authorization, tenant, origin)
    return Response(status_code=200, headers={CONTEXT_HEADER: token})


class SessionMembership(BaseModel):
    tenant_id: uuid.UUID
    tenant_slug: str
    tenant_name: str
    role: str
    status: str


async def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing credentials")
    return authorization[7:].strip()


@public_router.get("/v1/session/memberships", response_model=list[SessionMembership])
async def my_memberships(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> list[SessionMembership]:
    """Tenants the signed-in user belongs to (pending invites to a verified email are accepted)."""
    access = _access(request)
    claims = await access.idp.verify(await _bearer(authorization))
    async with access.db.scoped({"idp_issuer": claims.issuer, "idp_subject": claims.subject}) as s:
        user = await access.upsert_user(s, claims)
        await access.accept_invites(s, user, claims)
        rows = (
            await s.execute(
                select(Membership, Tenant)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .where(Membership.user_id == user.id, Membership.status == "active")
                .order_by(Tenant.name)
            )
        ).all()
    return [
        SessionMembership(
            tenant_id=t.id, tenant_slug=t.slug, tenant_name=t.name, role=m.role, status=m.status
        )
        for m, t in rows
    ]


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str
    region: str = "default"
    locale: str = "en"

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG.match(v):
            raise ValueError("lowercase letters, digits and dashes; 3-63 chars")
        return v


class TenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    region: str
    plan: str
    locale: str
    status: str
    deployment_mode: str

    @classmethod
    def of(cls, t: Tenant) -> TenantOut:
        return cls(
            id=t.id,
            slug=t.slug,
            name=t.name,
            region=t.region,
            plan=t.plan,
            locale=t.locale,
            status=t.status,
            deployment_mode=t.deployment_mode,
        )


@public_router.post("/v1/session/tenants", response_model=TenantOut, status_code=201)
async def create_tenant(
    body: TenantCreate, request: Request, authorization: Annotated[str | None, Header()] = None
) -> TenantOut:
    """Self-serve tenant creation for Keycloak/Auth0/OIDC sign-ups. The creator becomes owner."""
    access = _access(request)
    claims = await access.idp.verify(await _bearer(authorization))
    tenant_id = uuid7()
    try:
        async with access.db.scoped(
            {
                "idp_issuer": claims.issuer,
                "idp_subject": claims.subject,
                "tenant_id": str(tenant_id),
            }
        ) as s:
            user = await access.upsert_user(s, claims)
            tenant = Tenant(
                id=tenant_id, slug=body.slug, name=body.name, region=body.region, locale=body.locale
            )
            s.add(tenant)
            await s.flush()
            membership = Membership(
                tenant_id=tenant_id, user_id=user.id, role="owner", status="active"
            )
            s.add(membership)
            await s.flush()
            ctx = TenantContext(tenant_id=tenant_id, actor_id=str(user.id), actor_type="user")
            _event(s, ctx, "tenant.created", tenant_id, slug=body.slug, via="self-serve")
    except IntegrityError as exc:
        raise Conflict("That slug is already taken") from exc
    return TenantOut.of(tenant)


@public_router.post("/v1/webhooks/clerk", include_in_schema=False)
async def clerk_webhook(request: Request) -> dict[str, str]:
    handler: ClerkWebhooks | None = request.app.state.clerk_webhooks
    secret = request.app.state.settings.clerk_webhook_secret
    if handler is None or secret is None:
        raise NotFound("Clerk webhooks are not configured")
    body = await request.body()
    verify_svix(secret.get_secret_value(), request.headers, body)
    try:
        event = json.loads(body)
    except ValueError as exc:
        raise BadRequest("Malformed webhook body") from exc
    return {"status": await handler.handle(event)}


# ======================================================================= tenant-scoped admin


@tenant_router.get(
    "/tenant",
    response_model=TenantOut,
    dependencies=[require_permission("identity.tenant.read", "tenant")],
)
async def get_tenant(ctx: Ctx, request: Request) -> TenantOut:
    async with _db(request).session(ctx) as s:
        tenant = await s.get(Tenant, ctx.tenant_id)
    if tenant is None:
        raise NotFound("Tenant not found")
    return TenantOut.of(tenant)


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    locale: str | None = Field(default=None, max_length=16)


@tenant_router.patch(
    "/tenant",
    response_model=TenantOut,
    dependencies=[require_permission("identity.tenant.write", "tenant")],
)
async def patch_tenant(body: TenantPatch, ctx: Ctx, request: Request) -> TenantOut:
    async with _db(request).session(ctx) as s:
        tenant = await s.get(Tenant, ctx.tenant_id)
        if tenant is None:
            raise NotFound("Tenant not found")
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(tenant, field, value)
        _event(
            s, ctx, "tenant.updated", tenant.id, fields=sorted(body.model_dump(exclude_none=True))
        )
    return TenantOut.of(tenant)


# --------------------------------------------------------------------- members

Role = Literal["owner", "admin", "editor", "member"]


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    email: str | None
    display_name: str | None
    role: str
    status: str
    created_at: datetime


class MemberInvite(BaseModel):
    email: EmailStr
    role: Role = "member"


class MemberPatch(BaseModel):
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None


async def _require_owner_rights(request: Request, ctx: TenantContext) -> None:
    decision = await request.app.state.authorizer.decide(
        ctx, request.state.context_token, "identity.owners.write", Resource(type="membership")
    )
    if not decision.allow:
        raise Forbidden("Only owners can grant or change the owner role")


async def _active_owner_count(s: AsyncSession, tenant_id: uuid.UUID) -> int:
    count = await s.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.role == "owner",
            Membership.status == "active",
        )
    )
    return int(count or 0)


def _member_out(m: Membership, u: User | None) -> MemberOut:
    return MemberOut(
        id=m.id,
        user_id=m.user_id,
        email=(u.email if u else m.invited_email),
        display_name=u.display_name if u else None,
        role=m.role,
        status=m.status,
        created_at=m.created_at,
    )


@tenant_router.get(
    "/members",
    response_model=list[MemberOut],
    dependencies=[require_permission("identity.members.read", "membership")],
)
async def list_members(ctx: Ctx, request: Request) -> list[MemberOut]:
    async with _db(request).session(ctx) as s:
        rows = (
            await s.execute(
                select(Membership, User)
                .outerjoin(User, User.id == Membership.user_id)
                .order_by(Membership.created_at)
            )
        ).all()
    return [_member_out(m, u) for m, u in rows]


@tenant_router.post(
    "/members",
    response_model=MemberOut,
    status_code=201,
    dependencies=[require_permission("identity.members.write", "membership")],
)
async def invite_member(body: MemberInvite, ctx: Ctx, request: Request) -> MemberOut:
    if body.role == "owner":
        await _require_owner_rights(request, ctx)
    email = str(body.email).lower()
    try:
        async with _db(request).session(ctx) as s:
            m = Membership(
                tenant_id=ctx.tenant_id,
                invited_email=email,
                role=body.role,
                status="invited",
                invited_by=ctx.actor_id,
            )
            s.add(m)
            await s.flush()
            _event(s, ctx, "membership.invited", m.id, role=body.role)
    except IntegrityError as exc:
        raise Conflict("That person is already a member or invited") from exc
    return _member_out(m, None)


@tenant_router.patch(
    "/members/{member_id}",
    response_model=MemberOut,
    dependencies=[require_permission("identity.members.write", "membership")],
)
async def update_member(
    member_id: uuid.UUID, body: MemberPatch, ctx: Ctx, request: Request
) -> MemberOut:
    async with _db(request).session(ctx) as s:
        m = await s.get(Membership, member_id)
        if m is None:
            raise NotFound("Member not found")
        if m.role == "owner" or body.role == "owner":
            await _require_owner_rights(request, ctx)
        demotes_owner = m.role == "owner" and (
            body.role not in (None, "owner") or body.status == "disabled"
        )
        if (
            demotes_owner
            and m.status == "active"
            and await _active_owner_count(s, ctx.tenant_id) <= 1
        ):
            raise Conflict("A tenant must keep at least one active owner")
        if body.role is not None:
            m.role = body.role
        if body.status is not None:
            if m.status == "invited":
                raise BadRequest("Invitations cannot change status; remove and re-invite instead")
            m.status = body.status
        u = await s.get(User, m.user_id) if m.user_id else None
        _event(s, ctx, "membership.updated", m.id, role=m.role, status=m.status)
        return _member_out(m, u)


@tenant_router.delete(
    "/members/{member_id}",
    status_code=204,
    dependencies=[require_permission("identity.members.write", "membership")],
)
async def remove_member(member_id: uuid.UUID, ctx: Ctx, request: Request) -> Response:
    async with _db(request).session(ctx) as s:
        m = await s.get(Membership, member_id)
        if m is None:
            raise NotFound("Member not found")
        if m.role == "owner":
            await _require_owner_rights(request, ctx)
            if m.status == "active" and await _active_owner_count(s, ctx.tenant_id) <= 1:
                raise Conflict("A tenant must keep at least one active owner")
        await s.delete(m)
        _event(s, ctx, "membership.removed", member_id)
    return Response(status_code=204)


# --------------------------------------------------------------------- groups


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[\w .-]+$")
    description: str = Field(default="", max_length=500)


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    member_ids: list[uuid.UUID]


@tenant_router.get(
    "/groups",
    response_model=list[GroupOut],
    dependencies=[require_permission("identity.groups.read", "group")],
)
async def list_groups(ctx: Ctx, request: Request) -> list[GroupOut]:
    async with _db(request).session(ctx) as s:
        groups = (await s.scalars(select(Group).order_by(Group.name))).all()
        links = (await s.execute(select(GroupMember.group_id, GroupMember.membership_id))).all()
    members: dict[uuid.UUID, list[uuid.UUID]] = {}
    for gid, mid in links:
        members.setdefault(gid, []).append(mid)
    return [
        GroupOut(id=g.id, name=g.name, description=g.description, member_ids=members.get(g.id, []))
        for g in groups
    ]


@tenant_router.post(
    "/groups",
    response_model=GroupOut,
    status_code=201,
    dependencies=[require_permission("identity.groups.write", "group")],
)
async def create_group(body: GroupIn, ctx: Ctx, request: Request) -> GroupOut:
    try:
        async with _db(request).session(ctx) as s:
            g = Group(tenant_id=ctx.tenant_id, name=body.name, description=body.description)
            s.add(g)
            await s.flush()
            _event(s, ctx, "group.created", g.id, name=g.name)
    except IntegrityError as exc:
        raise Conflict("A group with that name exists") from exc
    return GroupOut(id=g.id, name=g.name, description=g.description, member_ids=[])


@tenant_router.delete(
    "/groups/{group_id}",
    status_code=204,
    dependencies=[require_permission("identity.groups.write", "group")],
)
async def delete_group(group_id: uuid.UUID, ctx: Ctx, request: Request) -> Response:
    async with _db(request).session(ctx) as s:
        g = await s.get(Group, group_id)
        if g is None:
            raise NotFound("Group not found")
        await s.delete(g)
        _event(s, ctx, "group.deleted", group_id)
    return Response(status_code=204)


@tenant_router.put(
    "/groups/{group_id}/members/{member_id}",
    status_code=204,
    dependencies=[require_permission("identity.groups.write", "group")],
)
async def add_group_member(
    group_id: uuid.UUID, member_id: uuid.UUID, ctx: Ctx, request: Request
) -> Response:
    async with _db(request).session(ctx) as s:
        if await s.get(Group, group_id) is None or await s.get(Membership, member_id) is None:
            raise NotFound("Group or member not found")
        exists = await s.scalar(
            select(GroupMember.id).where(
                GroupMember.group_id == group_id, GroupMember.membership_id == member_id
            )
        )
        if exists is None:
            s.add(GroupMember(tenant_id=ctx.tenant_id, group_id=group_id, membership_id=member_id))
            _event(s, ctx, "group.member_added", group_id, membership_id=str(member_id))
    return Response(status_code=204)


@tenant_router.delete(
    "/groups/{group_id}/members/{member_id}",
    status_code=204,
    dependencies=[require_permission("identity.groups.write", "group")],
)
async def remove_group_member(
    group_id: uuid.UUID, member_id: uuid.UUID, ctx: Ctx, request: Request
) -> Response:
    async with _db(request).session(ctx) as s:
        link = await s.scalar(
            select(GroupMember).where(
                GroupMember.group_id == group_id, GroupMember.membership_id == member_id
            )
        )
        if link is None:
            raise NotFound("Not a member of that group")
        await s.delete(link)
        _event(s, ctx, "group.member_removed", group_id, membership_id=str(member_id))
    return Response(status_code=204)


# --------------------------------------------------------------------- API keys


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["server", "widget"]
    roles: list[str] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)
    agent_ids: list[str] = Field(default_factory=list)
    # QA-02: must carry a timezone (e.g. "2099-01-01T00:00:00Z"); naive values are rejected with 422.
    expires_at: AwareDatetime | None = None

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, v: list[str]) -> list[str]:
        for origin in v:
            if not re.match(r"^https?://[a-z0-9.-]+(:\d+)?$", origin):
                raise ValueError(f"origin must look like https://example.com, got {origin!r}")
        return v


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    prefix: str
    roles: list[str]
    allowed_origins: list[str]
    agent_ids: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, k: ApiKey) -> ApiKeyOut:
        return cls(
            id=k.id,
            name=k.name,
            kind=k.kind,
            prefix=k.prefix,
            roles=k.roles,
            allowed_origins=k.allowed_origins,
            agent_ids=k.agent_ids,
            expires_at=k.expires_at,
            revoked_at=k.revoked_at,
            last_used_at=k.last_used_at,
            created_at=k.created_at,
        )


class ApiKeyCreated(ApiKeyOut):
    secret: str = Field(description="Shown once. Store it securely; it cannot be retrieved again.")


@tenant_router.get(
    "/api-keys",
    response_model=list[ApiKeyOut],
    dependencies=[require_permission("identity.api_keys.read", "api_key")],
)
async def list_keys(ctx: Ctx, request: Request) -> list[ApiKeyOut]:
    async with _db(request).session(ctx) as s:
        rows = (await s.scalars(select(ApiKey).order_by(ApiKey.created_at))).all()
    return [ApiKeyOut.of(k) for k in rows]


@tenant_router.post(
    "/api-keys",
    response_model=ApiKeyCreated,
    status_code=201,
    dependencies=[require_permission("identity.api_keys.write", "api_key")],
)
async def create_key(body: ApiKeyIn, ctx: Ctx, request: Request) -> ApiKeyCreated:
    if body.kind == "widget":
        if not body.allowed_origins:
            raise BadRequest("Widget keys need at least one allowed origin")
        roles = body.roles or ["end_user"]
        if roles != ["end_user"]:
            raise BadRequest("Widget keys can only have the end_user role")
    else:
        roles = body.roles or ["member"]
        bad = sorted(set(roles) - set(KEY_ROLES))
        if bad:
            raise BadRequest(f"API keys cannot have roles {bad}; allowed: {list(KEY_ROLES)}")
    if body.expires_at is not None and body.expires_at <= datetime.now(UTC):
        raise BadRequest("expires_at must be in the future")
    full, prefix, secret_hash = apikeys.generate(body.kind)
    async with _db(request).session(ctx) as s:
        key = ApiKey(
            tenant_id=ctx.tenant_id,
            name=body.name,
            kind=body.kind,
            prefix=prefix,
            secret_hash=secret_hash,
            roles=roles,
            allowed_origins=body.allowed_origins,
            agent_ids=body.agent_ids,
            expires_at=body.expires_at,
            created_by=ctx.actor_id,
            meta={},
        )
        s.add(key)
        await s.flush()
        _event(s, ctx, "api_key.created", key.id, kind=body.kind, roles=roles)
    return ApiKeyCreated(**ApiKeyOut.of(key).model_dump(), secret=full)


@tenant_router.delete(
    "/api-keys/{key_id}",
    status_code=204,
    dependencies=[require_permission("identity.api_keys.write", "api_key")],
)
async def revoke_key(key_id: uuid.UUID, ctx: Ctx, request: Request) -> Response:
    async with _db(request).session(ctx) as s:
        key = await s.get(ApiKey, key_id)
        if key is None:
            raise NotFound("API key not found")
        if key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
            _event(s, ctx, "api_key.revoked", key_id)
    _access(request).cache.clear()  # a revoked key must stop working immediately on this node
    return Response(status_code=204)
