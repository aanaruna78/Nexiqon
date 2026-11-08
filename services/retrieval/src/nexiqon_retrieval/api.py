"""HTTP API for retrieval. Contract: contracts/openapi/retrieval.json.

Index write endpoints are service-only (``retrieval.index.write``: ingestion's service identity).
Search arrives in Phase 2 slice 3.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, insert, select

from nexiqon_core.authz import Resource, check_permission, require_permission
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import Conflict, NotFound, ServiceUnavailable
from nexiqon_core.tenancy import TenantContext, require_current_context
from nexiqon_retrieval.models import DIMENSIONS, IndexNode

public_router = APIRouter(tags=["retrieval"])
tenant_router = APIRouter(prefix="/v1", tags=["retrieval"])

Ctx = Annotated[TenantContext, Depends(require_current_context)]
LTREE = re.compile(r"^[A-Za-z0-9_]{1,64}(\.[A-Za-z0-9_]{1,64}){0,63}$")
MAX_NODES = 20_000
SEPARATOR = " \u203a "  # "Guide > Setup" style section paths


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


def _db(request: Request) -> TenantSessionFactory:
    db: TenantSessionFactory | None = request.app.state.db
    if db is None:
        raise ServiceUnavailable("Retrieval database is not configured")
    return db


# ===================================================================== index writes


class NodeIn(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None = None
    path: str = Field(max_length=4000)
    kind: Literal["document", "section", "chunk", "summary"]
    ordinal: int = Field(default=0, ge=0)
    title: str | None = Field(default=None, max_length=1000)
    heading_path: list[Annotated[str, Field(max_length=1000)]] = Field(
        default_factory=list, max_length=32
    )
    text: str = Field(default="", max_length=200_000)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    token_count: int = Field(default=0, ge=0)
    embedding: list[float] | None = None


class DocumentIn(BaseModel):
    collection_id: uuid.UUID
    version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=1000)
    source_uri: str | None = Field(default=None, max_length=2000)
    acl_groups: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=100
    )
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    embedding_model: str | None = Field(default=None, max_length=200)
    nodes: list[NodeIn] = Field(min_length=1, max_length=MAX_NODES)

    @model_validator(mode="after")
    def _tree(self) -> DocumentIn:
        by_id = {n.id: n for n in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("node ids must be unique")
        roots = [n for n in self.nodes if n.parent_id is None]
        if len(roots) != 1 or roots[0].kind != "document":
            raise ValueError("exactly one root node of kind 'document' is required")
        for n in self.nodes:
            if not LTREE.match(n.path):
                raise ValueError(f"invalid path {n.path!r}")
            if n.parent_id is not None:
                parent = by_id.get(n.parent_id)
                if parent is None:
                    raise ValueError(f"node {n.id} has a parent outside this document")
                if (
                    not n.path.startswith(parent.path + ".")
                    or n.path.count(".") != parent.path.count(".") + 1
                ):
                    raise ValueError(f"path {n.path!r} is not a child of {parent.path!r}")
                if parent.kind == "chunk":
                    raise ValueError("chunks cannot have children")
            if n.embedding is not None and len(n.embedding) != DIMENSIONS:
                raise ValueError(f"embeddings must have {DIMENSIONS} dimensions")
            if n.kind == "chunk" and n.embedding is None:
                raise ValueError("every chunk needs an embedding")
        return self


class IndexResult(BaseModel):
    document_id: uuid.UUID
    version: int
    nodes: int
    chunks: int
    replaced: int


# Service-only writes: authorization runs before the body is even validated.
@tenant_router.put(
    "/index/documents/{document_id}",
    response_model=IndexResult,
    dependencies=[require_permission("retrieval.index.write", "document")],
)
async def put_document(
    document_id: uuid.UUID, body: DocumentIn, request: Request, ctx: Ctx
) -> IndexResult:
    """Replace a document's whole tree atomically: old content is never retrievable afterwards."""
    heading = SEPARATOR.join
    async with _db(request).session(ctx) as s:
        current = await s.scalar(
            select(func.max(IndexNode.document_version)).where(IndexNode.document_id == document_id)
        )
        if current is not None and current > body.version:
            raise Conflict(f"Index already holds version {current} of this document")
        replaced = (
            await s.execute(delete(IndexNode).where(IndexNode.document_id == document_id))
        ).rowcount  # type: ignore[attr-defined]
        rows = [
            {
                "id": n.id,
                "tenant_id": ctx.tenant_id,
                "collection_id": body.collection_id,
                "document_id": document_id,
                "document_version": body.version,
                "parent_id": n.parent_id,
                "path": n.path,
                "kind": n.kind,
                "ordinal": n.ordinal,
                "title": n.title,
                "heading_path": n.heading_path,
                "heading_text": heading(n.heading_path),
                "text": n.text,
                "page_start": n.page_start,
                "page_end": n.page_end,
                "token_count": n.token_count,
                "source_uri": body.source_uri,
                "acl_groups": body.acl_groups,
                "classification": body.classification,
                "embedding_model": body.embedding_model if n.embedding is not None else None,
                "embedding": n.embedding,
            }
            for n in body.nodes
        ]
        for i in range(0, len(rows), 500):
            await s.execute(insert(IndexNode), rows[i : i + 500])
    return IndexResult(
        document_id=document_id,
        version=body.version,
        nodes=len(rows),
        chunks=sum(1 for n in body.nodes if n.kind == "chunk"),
        replaced=int(replaced or 0),
    )


class Deleted(BaseModel):
    deleted: int


@tenant_router.delete(
    "/index/documents/{document_id}",
    response_model=Deleted,
    dependencies=[require_permission("retrieval.index.write", "document")],
)
async def delete_document(document_id: uuid.UUID, request: Request, ctx: Ctx) -> Deleted:
    async with _db(request).session(ctx) as s:
        result = await s.execute(delete(IndexNode).where(IndexNode.document_id == document_id))
    return Deleted(deleted=int(result.rowcount or 0))  # type: ignore[attr-defined]


@tenant_router.delete(
    "/index/collections/{collection_id}",
    response_model=Deleted,
    dependencies=[require_permission("retrieval.index.write", "collection")],
)
async def delete_collection(collection_id: uuid.UUID, request: Request, ctx: Ctx) -> Deleted:
    async with _db(request).session(ctx) as s:
        result = await s.execute(delete(IndexNode).where(IndexNode.collection_id == collection_id))
    return Deleted(deleted=int(result.rowcount or 0))  # type: ignore[attr-defined]


# ===================================================================== index reads (outline, stats)


class OutlineNode(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    path: str
    kind: str
    title: str | None
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    token_count: int


class Outline(BaseModel):
    document_id: uuid.UUID
    version: int
    nodes: list[OutlineNode]


@tenant_router.get("/index/documents/{document_id}/outline", response_model=Outline)
async def outline(document_id: uuid.UUID, request: Request, ctx: Ctx) -> Outline:
    """The indexed tree of a document, in reading order (no text or vectors)."""
    await check_permission(
        request, "retrieval.index.read", Resource(type="document", id=str(document_id))
    )
    async with _db(request).session(ctx) as s:
        rows = (
            await s.scalars(
                select(IndexNode)
                .where(IndexNode.document_id == document_id)
                .order_by(IndexNode.path)
            )
        ).all()
    if not rows:
        raise NotFound("Document is not indexed")
    return Outline(
        document_id=document_id,
        version=rows[0].document_version,
        nodes=[
            OutlineNode(
                id=r.id,
                parent_id=r.parent_id,
                path=r.path,
                kind=r.kind,
                title=r.title,
                heading_path=list(r.heading_path),
                page_start=r.page_start,
                page_end=r.page_end,
                token_count=r.token_count,
            )
            for r in rows
        ],
    )


class CollectionStats(BaseModel):
    collection_id: uuid.UUID
    documents: int
    sections: int
    chunks: int
    tokens: int


@tenant_router.get("/index/collections/{collection_id}/stats", response_model=CollectionStats)
async def stats(collection_id: uuid.UUID, request: Request, ctx: Ctx) -> CollectionStats:
    await check_permission(
        request, "retrieval.index.read", Resource(type="collection", id=str(collection_id))
    )
    n = IndexNode
    async with _db(request).session(ctx) as s:
        row = (
            await s.execute(
                select(
                    func.count(func.distinct(n.document_id)),
                    func.count().filter(n.kind == "section"),
                    func.count().filter(n.kind == "chunk"),
                    func.coalesce(func.sum(n.token_count).filter(n.kind == "chunk"), 0),
                ).where(n.collection_id == collection_id)
            )
        ).one()
    return CollectionStats(
        collection_id=collection_id,
        documents=row[0],
        sections=row[1],
        chunks=row[2],
        tokens=int(row[3]),
    )
