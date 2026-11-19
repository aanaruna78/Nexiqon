"""HTTP API for config. Contract: contracts/openapi/config.json."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field

from nexiqon_config import kinds, packs
from nexiqon_config.diff import diff
from nexiqon_config.gate import blocked
from nexiqon_config.models import ENVIRONMENTS, ConfigObject, ConfigVersion
from nexiqon_config.store import Store, _defaults, canonical_digest, spec_hash
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


class PublishIn(BaseModel):
    # Publish although the release gate did not pass (admins only; recorded with the reason).
    override_reason: str | None = Field(default=None, min_length=10, max_length=500)


class GateOut(BaseModel):
    """The release-gate answer recorded with a publish (QA-02)."""

    passed: bool
    overridden: bool = False
    test_set: str
    run_id: str | None = None
    baseline_version: int | None = None
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    deltas: dict[str, float] = Field(default_factory=dict)


class PublishOut(VersionOut):
    gate: GateOut | None = None


async def _release_gate(
    request: Request, ctx: TenantContext, name: str, version: int, override: str | None
) -> GateOut | None:
    """Ask evaluation whether this agent version may be published (only when its spec has an
    enabled release gate). Raises when it may not, unless an admin overrides with a reason."""
    settings = request.app.state.settings
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, settings)
        obj = await store.get_object("agent", name)
        candidate = await store.version(obj, version)
        rule = (candidate.spec or {}).get("release_gate") or {}
        digest = candidate.spec_hash
        live = (await store.deployments(obj)).get(settings.gate_baseline_environment)
    if not rule.get("enabled"):
        return None
    if override is not None:
        await _allow(request, "config.release.override", "agent", name)
    token = str(request.state.context_token)
    try:
        result = await request.app.state.gate.check(token, name, version, digest, live, rule)
    except ServiceUnavailable:
        if override is None:
            raise
        result = {"passed": False, "reasons": [{"code": "evaluation_unavailable"}]}
    out = GateOut(
        passed=bool(result.get("passed")),
        test_set=str(rule["test_set"]),
        run_id=str(result["run_id"]) if result.get("run_id") else None,
        baseline_version=live if result.get("baseline_run_id") else None,
        reasons=list(result.get("reasons") or []),
        deltas=dict(result.get("deltas") or {}),
    )
    if not out.passed:
        if override is None:
            raise blocked(result)
        out.overridden = True
    return out


@tenant_router.post("/objects/{kind}/{name}/versions/{version}/publish", response_model=PublishOut)
async def publish(
    kind: str,
    name: str,
    version: int,
    request: Request,
    ctx: Ctx,
    body: Annotated[PublishIn | None, Body()] = None,
) -> PublishOut:
    """Publish a draft. An assistant with a release gate must first pass its evaluation (QA-02)."""
    await _allow(request, _write_action(_kind(kind)), kind, name)
    override = body.override_reason if body else None
    gate = await _release_gate(request, ctx, name, version, override) if kind == "agent" else None
    async with _db(request).session(ctx) as s:
        v = await Store(s, ctx, request.app.state.settings).publish(
            kind,
            name,
            version,
            gate=gate.model_dump() if gate else None,
            override_reason=override if gate and gate.overridden else None,
        )
        return PublishOut(**VersionOut.of(v).model_dump(), gate=gate)


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


class GalleryPack(BaseModel):
    name: str
    title: str
    description: str
    version: str
    locales: list[str]
    intents: int
    tools: list[str]
    starter_questions: list[str]
    installed_version: int | None  # deployed in dev


def _gallery(request: Request) -> dict[str, tuple[str, dict[str, Any]]]:
    """Packs shipped with the platform (ST-13): name -> (YAML text, stored spec)."""
    root = Path(request.app.state.settings.pack_gallery_dir)
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sorted(root.glob("*/pack.yaml")) if root.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        name, spec = packs.parse_pack(text)
        out[name] = (text, spec)
    return out


@tenant_router.get("/packs/gallery", response_model=list[GalleryPack])
async def pack_gallery(request: Request, ctx: Ctx) -> list[GalleryPack]:
    """Ready-made Domain Packs to start from, and whether each is live in dev already."""
    await _allow(request, "config.domain_pack.read", "domain_pack")
    gallery = _gallery(request)
    out = []
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        for name, (_, spec) in gallery.items():
            deployed = await store._deployed_version("domain_pack", name, "dev")
            meta = spec.get("metadata") or {}
            starters = ((spec.get("channels") or {}).get("widget") or {}).get(
                "starter_questions"
            ) or {}
            out.append(
                GalleryPack(
                    name=name,
                    title=str(meta.get("title") or name),
                    description=str(meta.get("description") or ""),
                    version=str(meta.get("pack_version") or ""),
                    locales=list(meta.get("locales") or ["en"]),
                    intents=len(spec.get("intents") or []),
                    tools=[str(t.get("name")) for t in spec.get("tools") or []],
                    starter_questions=list(starters.get("en") or next(iter(starters.values()), [])),
                    installed_version=deployed.version if deployed else None,
                )
            )
    return out


@tenant_router.post("/packs/gallery/{name}/install", response_model=VersionOut)
async def install_gallery_pack(name: str, request: Request, ctx: Ctx) -> VersionOut:
    """Import a ready-made pack, publish it and make it live in dev, in one step. Installing a
    pack whose content is already live changes nothing."""
    gallery = _gallery(request)
    if name not in gallery:
        raise NotFound(f"No ready-made pack {name!r}")
    await _allow(request, _write_action("domain_pack"), "domain_pack", name)
    await _allow(request, "config.deployments.write", "domain_pack", name)
    _, spec = gallery[name]
    async with _db(request).session(ctx) as s:
        store = Store(s, ctx, request.app.state.settings)
        deployed = await store._deployed_version("domain_pack", name, "dev")
        if deployed is not None and deployed.spec_hash == spec_hash(spec):
            return VersionOut.of(deployed)
        try:
            await store.get_object("domain_pack", name)
        except NotFound:
            await store.create("domain_pack", name, str(spec["metadata"].get("title", "")), spec)
            draft = await store.version(await store.get_object("domain_pack", name), 1)
        else:
            draft = await store.save_draft("domain_pack", name, spec, "installed from the gallery")
        published = await store.publish("domain_pack", name, draft.version)
        await store.deploy(
            "domain_pack", name, "dev", published.version, "installed from the gallery"
        )
        return VersionOut.of(published)


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


class DeployedObject(BaseModel):
    kind: str
    name: str
    environment: str
    version: int
    spec: dict[str, Any]


@tenant_router.get("/resolve/objects/{kind}/{name}", response_model=DeployedObject)
async def resolve_object(
    kind: str, name: str, request: Request, ctx: Ctx, environment: str = "dev"
) -> DeployedObject:
    """The version of an object deployed in an environment (e.g. tool definitions for tool-gateway)."""
    await _allow(request, f"config.{_kind(kind)}.read", kind, name)
    if environment not in ENVIRONMENTS:
        raise BadRequest(f"environment must be one of {ENVIRONMENTS}")
    async with _db(request).session(ctx) as s:
        version = await Store(s, ctx, request.app.state.settings)._deployed_version(
            kind, name, environment
        )
    if version is None:
        raise NotFound(f"{kind} {name!r} is not deployed in {environment}")
    return DeployedObject(
        kind=kind, name=name, environment=environment, version=version.version, spec=version.spec
    )


@tenant_router.get("/resolve/profiles/{kind}/{name}")
async def resolve_profile(
    kind: str, name: str, request: Request, ctx: Ctx, environment: str = "dev"
) -> dict[str, Any]:
    """Effective model/retrieval/retention profile for the data plane, with floors applied.

    Uses the narrow ``config.profiles.resolve`` permission so callers that may run inference
    (members, end users, widgets via the model gateway) never need read access to the registry.
    """
    await _allow(request, "config.profiles.resolve", _kind(kind), name)
    if environment not in ENVIRONMENTS:
        raise BadRequest(f"environment must be one of {ENVIRONMENTS}")
    async with _db(request).session(ctx) as s:
        return await Store(s, ctx, request.app.state.settings).resolve_profile(
            kind, name, environment
        )


@tenant_router.get("/profiles/{kind}")
async def list_profiles(
    kind: str, request: Request, ctx: Ctx, environment: str = "dev"
) -> list[dict[str, Any]]:
    """Profiles of a kind usable in an environment (built-in and deployed), for Studio pickers."""
    await _allow(request, "config.profiles.resolve", _kind(kind))
    if environment not in ENVIRONMENTS:
        raise BadRequest(f"environment must be one of {ENVIRONMENTS}")
    async with _db(request).session(ctx) as s:
        return await Store(s, ctx, request.app.state.settings).list_profiles(kind, environment)


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


@tenant_router.get("/vocabulary")
async def vocabulary(
    request: Request, ctx: Ctx, environment: str = "dev"
) -> dict[str, dict[str, str]]:
    """Domain terms per locale from the packs deployed in an environment (Studio and widget labels)."""
    await _allow(request, "config.vocabulary.read", "domain_pack")
    if environment not in ENVIRONMENTS:
        raise BadRequest(f"environment must be one of {ENVIRONMENTS}")
    async with _db(request).session(ctx) as s:
        snapshot = await Store(s, ctx, request.app.state.settings).deployed_specs(
            "domain_pack", environment
        )
    merged: dict[str, dict[str, str]] = {}
    for spec in snapshot:
        for term, labels in (spec.get("vocabulary") or {}).items():
            merged.setdefault(term, {}).update(labels)
    return merged
