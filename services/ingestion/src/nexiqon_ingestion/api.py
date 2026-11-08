"""HTTP API for ingestion. Contract: contracts/openapi/ingestion.json."""

from __future__ import annotations

import hashlib
import re
import uuid
from contextlib import suppress
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from nexiqon_core.authz import Resource, check_permission
from nexiqon_core.blobs import tenant_key
from nexiqon_core.errors import BadRequest, Conflict, NexiqonError, NotFound, ServiceUnavailable
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_core.workflows import TenantScope, workflow_id
from nexiqon_ingestion.models import Collection, Document, Run, Source
from nexiqon_ingestion.pipeline import Pipeline
from nexiqon_sdk import Manifest, PluginKind, Registry

public_router = APIRouter(tags=["ingestion"])
tenant_router = APIRouter(prefix="/v1", tags=["ingestion"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
NAME = r"^[a-z0-9][a-z0-9-]{1,62}$"
UPLOADS = "uploads"
FILENAME = re.compile(r"^[^/\\\x00-\x1f]{1,255}$")
Classification = Literal["public", "internal", "confidential", "restricted"]


class TooLarge(NexiqonError):
    status, code, title = 413, "too_large", "File too large"


class ContextEcho(BaseModel):
    tenant_id: str
    actor_id: str
    actor_type: str


@tenant_router.get("/context", response_model=ContextEcho)
async def context(ctx: Ctx) -> ContextEcho:
    """Echo the verified tenant context (used by isolation smoke tests)."""
    return ContextEcho(
        tenant_id=str(ctx.tenant_id), actor_id=ctx.actor_id, actor_type=ctx.actor_type
    )


def _pipeline(request: Request) -> Pipeline:
    pipeline: Pipeline | None = request.app.state.pipeline
    if pipeline is None:
        raise ServiceUnavailable("Ingestion storage is not configured")
    return pipeline


async def _allow(request: Request, action: str, kind: str, rid: object = None) -> None:
    await check_permission(request, action, Resource(type=kind, id=str(rid) if rid else None))


async def _start(request: Request, ctx: TenantContext, workflow: str, run: Run, *args: Any) -> None:
    client = request.app.state.temporal
    if client is None:
        raise ServiceUnavailable("Workflows are not available; try again shortly")
    scope = TenantScope.of(ctx)
    wid = workflow_id(scope, workflow.rsplit(".", 1)[-1].lower(), str(run.id))
    await client.start_workflow(
        workflow, args=[scope, *args], id=wid, task_queue=request.app.state.settings.task_queue
    )
    async with _pipeline(request).d.db.session(ctx) as s:
        stored = await s.get(Run, run.id)
        assert stored is not None
        stored.workflow_id = wid


# ===================================================================== plugins (connector gallery)


@tenant_router.get("/plugins", response_model=list[Manifest])
async def plugins(request: Request, ctx: Ctx, kind: PluginKind | None = None) -> list[Manifest]:
    """Installed connectors, parsers and chunkers with their configuration schemas."""
    await _allow(request, "ingestion.plugins.read", "plugin")
    registry: Registry = request.app.state.registry
    return registry.manifests(kind)


# ===================================================================== collections


class CollectionIn(BaseModel):
    name: str = Field(pattern=NAME)
    description: str = Field(default="", max_length=500)
    model_profile: str = Field(default="cloud-frontier", pattern=NAME)
    retrieval_profile: str = Field(default="standard", pattern=NAME)
    classification: Classification = "internal"
    acl_groups: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=100
    )


class CollectionPatch(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    model_profile: str | None = Field(default=None, pattern=NAME)
    retrieval_profile: str | None = Field(default=None, pattern=NAME)
    classification: Classification | None = None
    acl_groups: list[Annotated[str, Field(max_length=200)]] | None = Field(
        default=None, max_length=100
    )


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    model_profile: str
    retrieval_profile: str
    classification: str
    acl_groups: list[str]
    embedding_model: str | None
    documents: int = 0
    created_at: datetime


def _collection_out(c: Collection, documents: int = 0) -> CollectionOut:
    return CollectionOut(
        id=c.id,
        name=c.name,
        description=c.description,
        model_profile=c.model_profile,
        retrieval_profile=c.retrieval_profile,
        classification=c.classification,
        acl_groups=list(c.acl_groups),
        embedding_model=c.embedding_model,
        documents=documents,
        created_at=c.created_at,
    )


@tenant_router.post("/collections", response_model=CollectionOut, status_code=201)
async def create_collection(body: CollectionIn, request: Request, ctx: Ctx) -> CollectionOut:
    await _allow(request, "ingestion.collections.write", "collection")
    try:
        async with _pipeline(request).d.db.session(ctx) as s:
            c = Collection(tenant_id=ctx.tenant_id, created_by=ctx.actor_id, **body.model_dump())
            s.add(c)
            await s.flush()
            s.add(
                Source(
                    tenant_id=ctx.tenant_id,
                    collection_id=c.id,
                    name=UPLOADS,
                    connector="upload",
                    config={},
                    created_by=ctx.actor_id,
                )
            )
            await s.flush()
            await s.refresh(c)
            return _collection_out(c)
    except IntegrityError as exc:
        raise Conflict(f"A collection named {body.name!r} already exists") from exc


async def _get_collection(
    request: Request, ctx: TenantContext, collection_id: uuid.UUID
) -> Collection:
    async with _pipeline(request).d.db.session(ctx) as s:
        c = await s.get(Collection, collection_id)
    if c is None:
        raise NotFound("Collection not found")
    return c


def _live() -> Any:
    return Document.status != "deleted"


@tenant_router.get("/collections", response_model=list[CollectionOut])
async def list_collections(request: Request, ctx: Ctx) -> list[CollectionOut]:
    await _allow(request, "ingestion.collections.read", "collection")
    async with _pipeline(request).d.db.session(ctx) as s:
        rows = (await s.scalars(select(Collection).order_by(Collection.name))).all()
        counts = dict(
            (
                await s.execute(
                    select(Document.collection_id, func.count())
                    .where(_live())
                    .group_by(Document.collection_id)
                )
            ).all()
        )
    return [_collection_out(c, int(counts.get(c.id, 0))) for c in rows]


@tenant_router.get("/collections/{collection_id}", response_model=CollectionOut)
async def get_collection(collection_id: uuid.UUID, request: Request, ctx: Ctx) -> CollectionOut:
    await _allow(request, "ingestion.collections.read", "collection", collection_id)
    c = await _get_collection(request, ctx, collection_id)
    async with _pipeline(request).d.db.session(ctx) as s:
        n = await s.scalar(select(func.count()).where(Document.collection_id == c.id, _live()))
    return _collection_out(c, int(n or 0))


@tenant_router.patch("/collections/{collection_id}", response_model=CollectionOut)
async def update_collection(
    collection_id: uuid.UUID, body: CollectionPatch, request: Request, ctx: Ctx
) -> CollectionOut:
    """Changing the model profile, classification or access groups reindexes the collection."""
    await _allow(request, "ingestion.collections.write", "collection", collection_id)
    changes = body.model_dump(exclude_none=True)
    async with _pipeline(request).d.db.session(ctx) as s:
        c = await s.get(Collection, collection_id)
        if c is None:
            raise NotFound("Collection not found")
        reindex = any(
            k in changes and changes[k] != getattr(c, k)
            for k in ("model_profile", "retrieval_profile", "classification", "acl_groups")
        )
        for k, v in changes.items():
            setattr(c, k, v)
        if "model_profile" in changes:
            c.embedding_model = None  # the reindex records the new model
        out = _collection_out(c)
    if reindex:
        await _reindex(request, ctx, collection_id)
    return out


@tenant_router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(collection_id: uuid.UUID, request: Request, ctx: Ctx) -> Response:
    """Removes the index, every stored file and the collection."""
    await _allow(request, "ingestion.collections.write", "collection", collection_id)
    pipeline = _pipeline(request)
    await _get_collection(request, ctx, collection_id)
    await pipeline.d.index.delete_collection(ctx.tenant_id, collection_id)
    async with pipeline.d.db.session(ctx) as s:
        keys = (
            await s.scalars(
                select(Document.blob_key).where(Document.collection_id == collection_id)
            )
        ).all()
    for key in keys:
        if key:
            await pipeline.d.blobs.delete(key)
    async with pipeline.d.db.session(ctx) as s:
        c = await s.get(Collection, collection_id)
        if c is not None:
            await s.delete(c)
        pipeline._event(
            s, ctx, "collection.deleted", str(collection_id), {"collection_id": str(collection_id)}
        )
    return Response(status_code=204)


class RunOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    source_id: uuid.UUID | None
    kind: str
    status: str
    workflow_id: str | None
    discovered: int
    processed: int
    unchanged: int
    failed: int
    quarantined: int
    deleted: int
    truncated: bool
    warnings: list[dict[str, str]]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


async def _run_out(request: Request, ctx: TenantContext, run_id: uuid.UUID) -> RunOut:
    async with _pipeline(request).d.db.session(ctx) as s:
        run = await s.get(Run, run_id)
    if run is None:
        raise NotFound("Run not found")
    return RunOut.model_validate(run, from_attributes=True)


# ===================================================================== sources


class SourceIn(BaseModel):
    name: str = Field(pattern=NAME)
    connector: str = Field(pattern=NAME)
    config: dict[str, Any] = Field(default_factory=dict)
    schedule_hours: int | None = Field(default=None, ge=1, le=24 * 30)


class SourceOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    name: str
    connector: str
    config: dict[str, Any]
    schedule_hours: int | None
    status: str
    last_run_id: uuid.UUID | None
    last_synced_at: datetime | None


def _source_out(s: Source) -> SourceOut:
    return SourceOut(
        id=s.id,
        collection_id=s.collection_id,
        name=s.name,
        connector=s.connector,
        config=s.config,
        schedule_hours=s.schedule_hours,
        status=s.status,
        last_run_id=s.last_run_id,
        last_synced_at=s.last_synced_at,
    )


@tenant_router.post(
    "/collections/{collection_id}/sources", response_model=SourceOut, status_code=201
)
async def create_source(
    collection_id: uuid.UUID, body: SourceIn, request: Request, ctx: Ctx
) -> SourceOut:
    await _allow(request, "ingestion.sources.write", "source")
    registry: Registry = request.app.state.registry
    try:
        plugin = registry.get(PluginKind.CONNECTOR, body.connector)
    except Exception as exc:
        raise BadRequest(f"Unknown connector {body.connector!r}") from exc
    if "push" in plugin.manifest.capabilities:
        raise BadRequest("Uploads go to the collection's upload endpoint")
    errors = registry.validate_config(PluginKind.CONNECTOR, body.connector, body.config)
    if errors:
        problem = BadRequest("Connector configuration is invalid")
        problem.errors = [{"message": e} for e in errors]
        raise problem
    await _get_collection(request, ctx, collection_id)
    try:
        async with _pipeline(request).d.db.session(ctx) as s:
            src = Source(
                tenant_id=ctx.tenant_id,
                collection_id=collection_id,
                created_by=ctx.actor_id,
                **body.model_dump(),
            )
            s.add(src)
            await s.flush()
            await s.refresh(src)
            out = _source_out(src)
    except IntegrityError as exc:
        raise Conflict(f"A source named {body.name!r} already exists in this collection") from exc
    if body.schedule_hours:
        await _schedule(request, ctx, out)
    return out


async def _schedule(request: Request, ctx: TenantContext, source: SourceOut) -> None:
    """Periodic re-sync through a Temporal schedule (best effort when workflows are offline)."""
    client = request.app.state.temporal
    if client is None or source.schedule_hours is None:
        return
    from datetime import timedelta

    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleIntervalSpec,
        ScheduleSpec,
    )

    scope = TenantScope.of(ctx)
    await client.create_schedule(
        workflow_id(scope, "schedule", str(source.id)),
        Schedule(
            action=ScheduleActionStartWorkflow(
                "ingestion.SyncSource",
                args=[scope, None, str(source.id)],
                id=workflow_id(scope, "scheduled-sync", str(source.id)),
                task_queue=request.app.state.settings.task_queue,
            ),
            spec=ScheduleSpec(
                intervals=[ScheduleIntervalSpec(every=timedelta(hours=source.schedule_hours))]
            ),
        ),
    )


@tenant_router.get("/collections/{collection_id}/sources", response_model=list[SourceOut])
async def list_sources(collection_id: uuid.UUID, request: Request, ctx: Ctx) -> list[SourceOut]:
    await _allow(request, "ingestion.sources.read", "source")
    async with _pipeline(request).d.db.session(ctx) as s:
        rows = (
            await s.scalars(
                select(Source).where(Source.collection_id == collection_id).order_by(Source.name)
            )
        ).all()
    return [_source_out(r) for r in rows]


@tenant_router.post("/sources/{source_id}/sync", response_model=RunOut, status_code=202)
async def sync_source(source_id: uuid.UUID, request: Request, ctx: Ctx) -> RunOut:
    """Start a sync now; only changed content is re-embedded."""
    await _allow(request, "ingestion.sources.write", "source", source_id)
    async with _pipeline(request).d.db.session(ctx) as s:
        src = await s.get(Source, source_id)
        if src is None:
            raise NotFound("Source not found")
        if src.connector == "upload":
            raise BadRequest("Upload sources are not synced")
        if src.status == "syncing":
            raise Conflict("A sync is already running for this source")
        run = Run(
            tenant_id=ctx.tenant_id,
            collection_id=src.collection_id,
            source_id=src.id,
            kind="sync",
            created_by=ctx.actor_id,
        )
        s.add(run)
        src.status = "syncing"
        await s.flush()
        await s.refresh(run)
    try:
        await _start(
            request,
            ctx,
            "ingestion.SyncSource",
            run,
            str(run.id),
            str(source_id),
            request.app.state.settings.concurrency,
        )
    except Exception:
        async with _pipeline(request).d.db.session(ctx) as s:
            stored_src = await s.get(Source, source_id)
            stored_run = await s.get(Run, run.id)
            if stored_src is not None:
                stored_src.status = "idle"
            if stored_run is not None:
                stored_run.status, stored_run.error = "failed", "could not start"
        raise
    return await _run_out(request, ctx, run.id)


@tenant_router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: uuid.UUID, request: Request, ctx: Ctx) -> Response:
    """Deletes the source and every document it brought in (index and files)."""
    await _allow(request, "ingestion.sources.write", "source", source_id)
    pipeline = _pipeline(request)
    async with pipeline.d.db.session(ctx) as s:
        src = await s.get(Source, source_id)
        if src is None:
            raise NotFound("Source not found")
        if src.name == UPLOADS and src.connector == "upload":
            raise BadRequest("The uploads source belongs to the collection")
        ids = (await s.scalars(select(Document.id).where(Document.source_id == source_id))).all()
        schedule = src.schedule_hours
    for doc_id in ids:
        await pipeline.delete_document(ctx, doc_id)
    client = request.app.state.temporal
    if schedule and client is not None:
        with suppress(Exception):  # the schedule may already be gone
            await client.get_schedule_handle(
                workflow_id(TenantScope.of(ctx), "schedule", str(source_id))
            ).delete()
    async with pipeline.d.db.session(ctx) as s:
        src = await s.get(Source, source_id)
        if src is not None:
            await s.delete(src)
    return Response(status_code=204)


# ===================================================================== documents


class DocumentOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    source_id: uuid.UUID
    uri: str
    title: str | None
    media_type: str | None
    size: int
    version: int
    indexed_version: int | None
    status: str
    error_code: str | None
    error_detail: str | None
    scanner: str | None
    section_count: int
    chunk_count: int
    token_count: int
    updated_at: datetime
    indexed_at: datetime | None


def _doc_out(d: Document) -> DocumentOut:
    return DocumentOut.model_validate(d, from_attributes=True)


class UploadOut(BaseModel):
    document: DocumentOut
    run_id: uuid.UUID | None
    unchanged: bool


@tenant_router.post(
    "/collections/{collection_id}/documents", response_model=UploadOut, status_code=202
)
async def upload_document(
    collection_id: uuid.UUID,
    request: Request,
    ctx: Ctx,
    filename: Annotated[str, Query(max_length=255)],
) -> UploadOut:
    """Upload a file as the raw request body. Re-uploading the same filename replaces it."""
    await _allow(request, "ingestion.documents.write", "document")
    if not FILENAME.match(filename) or filename in (".", ".."):
        raise BadRequest("Invalid file name")
    pipeline = _pipeline(request)
    limit = request.app.state.settings.max_upload_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise TooLarge(f"Files are limited to {limit // (1024 * 1024)} MB")
    chunks: list[bytes] = []
    size = 0
    async for part in request.stream():
        size += len(part)
        if size > limit:
            raise TooLarge(f"Files are limited to {limit // (1024 * 1024)} MB")
        chunks.append(part)
    data = b"".join(chunks)
    if not data:
        raise BadRequest("The file is empty")
    media = (
        (request.headers.get("content-type") or "application/octet-stream")
        .split(";")[0]
        .strip()
        .lower()
    )
    digest = hashlib.sha256(data).hexdigest()
    uri = f"upload://{filename}"
    async with pipeline.d.db.session(ctx) as s:
        collection = await s.get(Collection, collection_id)
        if collection is None:
            raise NotFound("Collection not found")
        src = await s.scalar(
            select(Source).where(
                Source.collection_id == collection_id, Source.connector == "upload"
            )
        )
        assert src is not None
        doc = await s.scalar(
            select(Document).where(Document.source_id == src.id, Document.uri == uri)
        )
        if doc is not None and doc.status == "ready" and doc.content_hash == digest:
            return UploadOut(document=_doc_out(doc), run_id=None, unchanged=True)
        if doc is None:
            doc = Document(
                tenant_id=ctx.tenant_id,
                collection_id=collection_id,
                source_id=src.id,
                uri=uri,
                title=filename,
            )
            s.add(doc)
            await s.flush()
        doc.version += 1
        old_key = doc.blob_key
        doc.blob_key = tenant_key(ctx.tenant_id, "documents", str(doc.id), f"v{doc.version}")
        await pipeline.d.blobs.put(doc.blob_key, data, media)
        doc.content_hash, doc.size, doc.media_type = digest, len(data), media
        doc.status, doc.error_code, doc.error_detail, doc.scan_signature = (
            "pending",
            None,
            None,
            None,
        )
        run = Run(
            tenant_id=ctx.tenant_id,
            collection_id=collection_id,
            source_id=src.id,
            kind="upload",
            created_by=ctx.actor_id,
            discovered=1,
        )
        s.add(run)
        await s.flush()
        await s.refresh(doc)
        doc_id, run_id = doc.id, run.id
    if old_key and old_key != doc.blob_key:
        await pipeline.d.blobs.delete(old_key)
    await _start(request, ctx, "ingestion.IngestDocument", run, str(run_id), str(doc_id))
    async with pipeline.d.db.session(ctx) as s:
        fresh = await s.get(Document, doc_id)
        assert fresh is not None
        return UploadOut(document=_doc_out(fresh), run_id=run_id, unchanged=False)


@tenant_router.get("/collections/{collection_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    collection_id: uuid.UUID,
    request: Request,
    ctx: Ctx,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentOut]:
    await _allow(request, "ingestion.documents.read", "document")
    q = select(Document).where(Document.collection_id == collection_id)
    q = q.where(Document.status == status) if status else q.where(_live())
    async with _pipeline(request).d.db.session(ctx) as s:
        rows = (await s.scalars(q.order_by(Document.uri).limit(limit).offset(offset))).all()
    return [_doc_out(d) for d in rows]


@tenant_router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, request: Request, ctx: Ctx) -> DocumentOut:
    await _allow(request, "ingestion.documents.read", "document", document_id)
    async with _pipeline(request).d.db.session(ctx) as s:
        doc = await s.get(Document, document_id)
    if doc is None or doc.status == "deleted":
        raise NotFound("Document not found")
    return _doc_out(doc)


@tenant_router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: uuid.UUID, request: Request, ctx: Ctx) -> Response:
    """Removes the document from the index first, then its file: it is unretrievable on return."""
    await _allow(request, "ingestion.documents.write", "document", document_id)
    pipeline = _pipeline(request)
    async with pipeline.d.db.session(ctx) as s:
        doc = await s.get(Document, document_id)
    if doc is None or doc.status == "deleted":
        raise NotFound("Document not found")
    await pipeline.delete_document(ctx, document_id)
    return Response(status_code=204)


# ===================================================================== runs (live progress)


@tenant_router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, request: Request, ctx: Ctx) -> RunOut:
    await _allow(request, "ingestion.runs.read", "run", run_id)
    return await _run_out(request, ctx, run_id)


@tenant_router.get("/collections/{collection_id}/runs", response_model=list[RunOut])
async def list_runs(
    collection_id: uuid.UUID,
    request: Request,
    ctx: Ctx,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RunOut]:
    await _allow(request, "ingestion.runs.read", "run")
    async with _pipeline(request).d.db.session(ctx) as s:
        rows = (
            await s.scalars(
                select(Run)
                .where(Run.collection_id == collection_id)
                .order_by(Run.created_at.desc())
                .limit(limit)
            )
        ).all()
    return [RunOut.model_validate(r, from_attributes=True) for r in rows]


async def _reindex(request: Request, ctx: TenantContext, collection_id: uuid.UUID) -> RunOut:
    async with _pipeline(request).d.db.session(ctx) as s:
        run = Run(
            tenant_id=ctx.tenant_id,
            collection_id=collection_id,
            kind="reindex",
            created_by=ctx.actor_id,
        )
        s.add(run)
        await s.flush()
        await s.refresh(run)
    await _start(
        request,
        ctx,
        "ingestion.ReindexCollection",
        run,
        str(run.id),
        request.app.state.settings.concurrency,
    )
    return await _run_out(request, ctx, run.id)


@tenant_router.post("/collections/{collection_id}/reindex", response_model=RunOut, status_code=202)
async def reindex(collection_id: uuid.UUID, request: Request, ctx: Ctx) -> RunOut:
    """Reprocess every document from its stored file (new chunking or embedding model)."""
    await _allow(request, "ingestion.collections.write", "collection", collection_id)
    await _get_collection(request, ctx, collection_id)
    return await _reindex(request, ctx, collection_id)
