"""HTTP API for config. Contract: contracts/openapi/config.json."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field

from nexiqon_config import kinds, packs
from nexiqon_config.diff import diff
from nexiqon_config.models import ENVIRONMENTS, ConfigObject, ConfigVersion
from nexiqon_config.store import Store, _defaults, canonical_digest
from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import BadRequest, NotFound, ServiceUnavailable
from nexiqon_core.signing import jwks, sign
from nexiqon_core.tenancy import TenantContext, require_current_context

public_router = APIRouter(tags=["config"])
tenant_router = APIRouter(prefix="/v1", tags=["config"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
NAME = r"^[a-z0-9][a-z0-9-]{1,62}$"


def _db(request: Request) -> TenantSessionFactory:
    db: TenantSessionFactory | None = request.app.state.db
    if db is None:
        raise ServiceUnavailable("Config database is not configured")
    return db


def _kind(kind: str) -> str:
    if kind not in kinds.KINDS:
        raise NotFound(f"Unknown kind {kind!r}")
    return kind


def _write_action(kind: str) -> str:
    # Security floors are owner-only (see services/authz/policies).
    return "config.security_floors.write" if kind == "security_floors" else f"config.{kind}.write"


async def _allow(request: Request, action: str, kind: str, name: str | None = None) -> None:
    await check_permission(request, action, Resource(type=kind, id=name))


# ===================================================================== schemas (for Studio forms)


class KindInfo(BaseModel):
    kind: str
    title: str
    description: str
    json_schema: dict[str, Any] = Field(serialization_alias="schema")


@tenant_router.get("/kinds", response_model=list[KindInfo], response_model_by_alias=True)
async def list_kinds(request: Request, ctx: Ctx) -> list[KindInfo]:
    """All configuration kinds with JSON Schemas (including x-ui hints for generated forms)."""
    await _allow(request, "config.kinds.read", "kind")
    return [
        KindInfo(
            kind=k,
            title=kinds.schema(k).get("title", k),
            description=kinds.schema(k).get("description", ""),
            json_schema=kinds.schema(k),
        )
        for k in kinds.KINDS
    ]


# ===================================================================== objects and versions


class VersionOut(BaseModel):
    version: int
    status: str
    spec_hash: str
    notes: str
    created_by: str
    created_at: datetime
    published_by: str | None
    published_at: datetime | None

    @classmethod
    def of(cls, v: ConfigVersion) -> VersionOut:
        return cls(
            version=v.version,
            status=v.status,
            spec_hash=v.spec_hash,
            notes=v.notes,
            created_by=v.created_by,
            created_at=v.created_at,
            published_by=v.published_by,
            published_at=v.published_at,
        )


class VersionDetail(VersionOut):
    spec: dict[str, Any]


class ObjectOut(BaseModel):
    kind: str
    name: str
    description: str
    versions: list[VersionOut]
    deployments: dict[str, int]


async def _object_out(store: Store, obj: ConfigObject) -> ObjectOut:
    return ObjectOut(
        kind=obj.kind,
        name=obj.name,
        description=obj.description,
        versions=[VersionOut.of(v) for v in await store.versions(obj)],
        deployments=await store.deployments(obj),
    )


class ObjectCreate(BaseModel):
    kind: str
    name: str = Field(pattern=NAME)
    description: str = Field(default="", max_length=500)
    spec: dict[str, Any]


class DraftIn(BaseModel):
    spec: dict[str, Any]
    notes: str = Field(default="", max_length=1000)


@tenant_router.get("/objects", response_model=list[ObjectOut])
async def list_objects(request: Request, ctx: Ctx, kind: str | None = None) -> list[ObjectOut]:
    await _allow(request, f"config.{_kind(kind) if kind else 'objects'}.read", kind or "config")
    from sqlalchemy import select

    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        stmt = select(ConfigObject).where(ConfigObject.archived_at.is_(None))
        if kind:
            stmt = stmt.where(ConfigObject.kind == kind)
        objs = (await s.scalars(stmt.order_by(ConfigObject.kind, ConfigObject.name))).all()
        return [await _object_out(store, o) for o in objs]


@tenant_router.post("/objects", response_model=ObjectOut, status_code=201)
async def create_object(body: ObjectCreate, request: Request, ctx: Ctx) -> ObjectOut:
    kind = _kind(body.kind)
    await _allow(request, _write_action(kind), kind, body.name)
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        await store.create(kind, body.name, body.description, body.spec)
        return await _object_out(store, await store.get_object(kind, body.name))


@tenant_router.get("/objects/{kind}/{name}", response_model=ObjectOut)
async def get_object(kind: str, name: str, request: Request, ctx: Ctx) -> ObjectOut:
    await _allow(request, f"config.{_kind(kind)}.read", kind, name)
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        return await _object_out(store, await store.get_object(kind, name))


@tenant_router.delete("/objects/{kind}/{name}", status_code=204)
async def archive_object(kind: str, name: str, request: Request, ctx: Ctx) -> Response:
    await _allow(request, _write_action(_kind(kind)), kind, name)
    async with _db(request).session(ctx) as s:
        await Store(s, ctx, request.app.state.settings).archive(kind, name)
    return Response(status_code=204)


@tenant_router.put("/objects/{kind}/{name}/draft", response_model=VersionDetail)
async def save_draft(
    kind: str, name: str, body: DraftIn, request: Request, ctx: Ctx
) -> VersionDetail:
    await _allow(request, _write_action(_kind(kind)), kind, name)
    async with _db(request).session(ctx) as s:
        v = await Store(s, ctx, request.app.state.settings).save_draft(
            kind, name, body.spec, body.notes
        )
        return VersionDetail(**VersionOut.of(v).model_dump(), spec=v.spec)


@tenant_router.get("/objects/{kind}/{name}/versions/{version}", response_model=VersionDetail)
async def get_version(
    kind: str, name: str, version: int, request: Request, ctx: Ctx
) -> VersionDetail:
    await _allow(request, f"config.{_kind(kind)}.read", kind, name)
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        v = await store.version(await store.get_object(kind, name), version)
        return VersionDetail(**VersionOut.of(v).model_dump(), spec=v.spec)


@tenant_router.post("/objects/{kind}/{name}/versions/{version}/publish", response_model=VersionOut)
async def publish(kind: str, name: str, version: int, request: Request, ctx: Ctx) -> VersionOut:
    await _allow(request, _write_action(_kind(kind)), kind, name)
    async with _db(request).session(ctx) as s:
        v = await Store(s, ctx, request.app.state.settings).publish(kind, name, version)
        return VersionOut.of(v)


@tenant_router.get("/objects/{kind}/{name}/diff")
async def diff_versions(
    kind: str,
    name: str,
    request: Request,
    ctx: Ctx,
    from_version: Annotated[int, Query(alias="from")],
    to_version: Annotated[int, Query(alias="to")],
) -> dict[str, Any]:
    """Structural diff between two versions (Studio shows it next to the evaluation score diff)."""
    await _allow(request, f"config.{_kind(kind)}.read", kind, name)
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        obj = await store.get_object(kind, name)
        old, new = await store.version(obj, from_version), await store.version(obj, to_version)
        return {"from": from_version, "to": to_version, "changes": diff(old.spec, new.spec)}


# ===================================================================== deployments


class DeployIn(BaseModel):
    version: int = Field(ge=1)
    reason: str = Field(default="", max_length=500)


class HistoryOut(BaseModel):
    environment: str
    from_version: int | None
    to_version: int
    actor: str
    reason: str
    at: datetime


@tenant_router.put("/objects/{kind}/{name}/deployments/{environment}")
async def deploy(
    kind: str, name: str, environment: str, body: DeployIn, request: Request, ctx: Ctx
) -> dict[str, Any]:
    """Deploy or promote a published version. Rolling back = deploying an earlier version."""
    _kind(kind)
    action = (
        "config.security_floors.write" if kind == "security_floors" else "config.deployments.write"
    )
    await _allow(request, action, kind, name)
    async with _db(request).session(ctx) as s:
        d = await Store(s, ctx, request.app.state.settings).deploy(
            kind, name, environment, body.version, body.reason
        )
        return {"kind": kind, "name": name, "environment": d.environment, "version": d.version}


@tenant_router.delete("/objects/{kind}/{name}/deployments/{environment}", status_code=204)
async def undeploy(kind: str, name: str, environment: str, request: Request, ctx: Ctx) -> Response:
    _kind(kind)
    action = (
        "config.security_floors.write" if kind == "security_floors" else "config.deployments.write"
    )
    await _allow(request, action, kind, name)
    async with _db(request).session(ctx) as s:
        await Store(s, ctx, request.app.state.settings).undeploy(kind, name, environment)
    return Response(status_code=204)


@tenant_router.get("/objects/{kind}/{name}/deployments/history", response_model=list[HistoryOut])
async def deployment_history(kind: str, name: str, request: Request, ctx: Ctx) -> list[HistoryOut]:
    await _allow(request, f"config.{_kind(kind)}.read", kind, name)
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        rows = await store.history(await store.get_object(kind, name))
        return [
            HistoryOut(
                environment=h.environment,
                from_version=h.from_version,
                to_version=h.to_version,
                actor=h.actor,
                reason=h.reason,
                at=h.created_at,
            )
            for h in rows
        ]


# ===================================================================== Domain Packs (GitOps)


@tenant_router.post("/packs/import", response_model=VersionDetail, status_code=201)
async def import_pack(
    request: Request,
    ctx: Ctx,
    content: Annotated[str, Body(media_type="application/yaml")],
) -> VersionDetail:
    """Import a Domain Pack YAML file: creates the pack or saves a new draft version."""
    name, spec = packs.parse_pack(content)
    await _allow(request, _write_action("domain_pack"), "domain_pack", name)
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        try:
            await store.get_object("domain_pack", name)
        except NotFound:
            await store.create("domain_pack", name, spec.get("metadata", {}).get("title", ""), spec)
            v = await store.version(await store.get_object("domain_pack", name), 1)
        else:
            v = await store.save_draft("domain_pack", name, spec, "imported")
        return VersionDetail(**VersionOut.of(v).model_dump(), spec=v.spec)


@tenant_router.get("/packs/{name}/export", response_class=Response)
async def export_pack(
    name: str, request: Request, ctx: Ctx, version: int | None = None
) -> Response:
    await _allow(request, "config.domain_pack.read", "domain_pack", name)
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        obj = await store.get_object("domain_pack", name)
        versions = await store.versions(obj)
        chosen = (
            next((v for v in versions if v.version == version), None) if version else versions[-1]
        )
        if chosen is None:
            raise NotFound(f"No version {version}")
        return Response(packs.render_pack(name, chosen.spec), media_type="application/yaml")


# ===================================================================== resolution and snapshots


@tenant_router.get("/resolve/agents/{name}")
async def resolve_agent(
    name: str,
    request: Request,
    ctx: Ctx,
    environment: str = "dev",
    channel: str | None = None,
    version: int | None = None,
) -> dict[str, Any]:
    """The agent as the runtime will see it: every layer merged, profiles inlined, floors checked,
    with per-field provenance. ``version`` previews a specific (even draft) agent version."""
    await _allow(request, "config.agent.read", "agent", name)
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        preview = (
            await store.version(await store.get_object("agent", name), version) if version else None
        )
        return await store.resolve_agent(name, environment, channel=channel, agent_version=preview)


@tenant_router.get("/snapshots/{environment}")
async def snapshot(
    environment: str,
    request: Request,
    ctx: Ctx,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Signed bundle of everything deployed in an environment, pulled by data planes (CF-05)."""
    await _allow(request, "config.snapshots.read", "snapshot")
    if environment not in ENVIRONMENTS:
        raise BadRequest(f"environment must be one of {ENVIRONMENTS}")
    signing = request.app.state.settings.snapshot_signing
    if not signing.configured:
        raise ServiceUnavailable("Snapshot signing is not configured")
    async with _db(request).session(ctx) as s:
        body = await Store(s, ctx, request.app.state.settings).snapshot(environment)
    digest = canonical_digest(body)
    etag = f'"{digest}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    signature = sign(
        signing,
        {
            "digest": digest,
            "tenant_id": body["tenant_id"],
            "environment": environment,
            "iat": int(time.time()),
        },
    )
    import json

    payload = json.dumps({"snapshot": body, "digest": digest, "signature": signature})
    return Response(payload, media_type="application/json", headers={"ETag": etag})


@public_router.get("/.well-known/jwks.json", include_in_schema=False)
async def snapshot_keys(request: Request) -> dict[str, Any]:
    """Public keys for verifying configuration snapshots."""
    return jwks(request.app.state.settings.snapshot_signing)


class FlagOut(BaseModel):
    key: str
    description: str
    enabled: bool


@tenant_router.get("/flags", response_model=list[FlagOut])
async def flags(request: Request, ctx: Ctx) -> list[FlagOut]:
    """Feature flags evaluated for the caller's tenant (Studio and widget read these)."""
    await _allow(request, "config.flags.read", "flag")
    evaluator = request.app.state.flags
    return [
        FlagOut(
            key=f["key"],
            description=f.get("description", ""),
            enabled=evaluator.enabled(f["key"], ctx, default=bool(f.get("default", False))),
        )
        for f in _defaults("flags").get("flags", [])
    ]
