"""Ingestion activities: discover -> fetch -> scan -> parse -> chunk -> embed -> index (IN-02).

Every activity is idempotent and derives its tenant only from the workflow's ``TenantScope``, so
RLS confines it to that tenant. Failures that retrying cannot fix mark the document ``failed`` with
an ``error_code`` (shown in Studio with a fix hint) and do not fail the run.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity
from temporalio.exceptions import ApplicationError

from nexiqon_core.blobs import BlobNotFound, BlobStore, tenant_key
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.errors import NexiqonError
from nexiqon_core.events import add_event
from nexiqon_core.fetch import FetchBlocked, FetchFailed, FetchTooLarge, SafeFetcher
from nexiqon_core.profiles import ProfileResolver
from nexiqon_core.scanning import Scanner, ScanUnavailable
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.tenancy import TenantContext
from nexiqon_core.workflows import TenantScope
from nexiqon_ingestion.clients import Embedder, IndexClient, PermanentError, TransientError
from nexiqon_ingestion.models import Collection, Document, Outbox, Run, Source
from nexiqon_ingestion.plugins.context import Context, MissingCredentials
from nexiqon_ingestion.settings import ServiceSettings
from nexiqon_ingestion.tree import build_tree, embedding_text
from nexiqon_ingestion.wf_types import Discovery, FetchOutcome, ItemRef
from nexiqon_sdk import Item, PluginKind, Registry

log = structlog.get_logger(__name__)
SERVICE = "ingestion"
MAX_WARNINGS = 100
DEFAULT_CHUNKING = {"strategy": "heading-aware", "max_tokens": 400, "overlap_tokens": 40}


def permanent(code: str, detail: str) -> ApplicationError:
    return ApplicationError(detail[:500], code, type="PermanentError", non_retryable=True)


@dataclass
class Deps:
    settings: ServiceSettings
    db: TenantSessionFactory
    blobs: BlobStore
    scanner: Scanner
    registry: Registry
    fetcher: SafeFetcher
    tokens: ServiceTokens
    embedder: Embedder
    index: IndexClient
    retrieval_profiles: ProfileResolver
    connector_transport: Any = None  # tests: mock transport for connector-owned HTTP clients


class Pipeline:
    def __init__(self, deps: Deps) -> None:
        self.d = deps

    # ------------------------------------------------------------------ helpers

    def _ctx(self, scope: TenantScope) -> TenantContext:
        return self.d.tokens.context(scope.context().tenant_id)

    def _context(self, scope: TenantScope, run_id: str) -> Context:
        tenant = scope.context().tenant_id
        return Context(
            tenant_id=tenant,
            http=self.d.fetcher,
            blobs=self.d.blobs,
            scratch=self.d.settings.scratch_dir / str(tenant) / run_id,
            credentials=self.d.settings.connector_credentials,
            max_items=self.d.settings.max_items_per_sync,
            max_bytes=self.d.settings.fetch.max_bytes,
            transport=self.d.connector_transport,
        )

    async def _bump(self, s: AsyncSession, run_id: str, **counters: int) -> None:
        values = {k: getattr(Run, k) + v for k, v in counters.items()}
        await s.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(**values))

    def _event(
        self, s: AsyncSession, ctx: TenantContext, kind: str, subject: str, data: dict[str, Any]
    ) -> None:
        add_event(
            s,
            Outbox,
            ctx,
            source=SERVICE,
            type=f"nexiqon.ingestion.{kind}",
            subject=subject,
            data=data,
        )

    async def _fail(
        self,
        s: AsyncSession,
        ctx: TenantContext,
        doc: Document,
        run_id: str | None,
        code: str,
        detail: str,
    ) -> None:
        doc.status, doc.error_code, doc.error_detail = "failed", code, detail[:1000]
        if run_id:
            await self._bump(s, run_id, failed=1)
        self._event(
            s, ctx, "document.failed", str(doc.id), {"document_id": str(doc.id), "error_code": code}
        )

    # ------------------------------------------------------------------ runs

    @activity.defn(name="ingestion.start_run")
    async def start_run(self, scope: TenantScope, source_id: str) -> str:
        """Create a run for a scheduled sync (API-started syncs create theirs up front)."""
        ctx = self._ctx(scope)
        async with self.d.db.session(ctx) as s:
            source = await s.get(Source, uuid.UUID(source_id))
            if source is None:
                raise permanent("not_found", "source no longer exists")
            run = Run(
                tenant_id=ctx.tenant_id,
                collection_id=source.collection_id,
                source_id=source.id,
                kind="sync",
                created_by="schedule",
                workflow_id=activity.info().workflow_id,
            )
            s.add(run)
            await s.flush()
            return str(run.id)

    @activity.defn(name="ingestion.discover")
    async def discover(self, scope: TenantScope, run_id: str) -> Discovery:
        ctx = self._ctx(scope)
        async with self.d.db.session(ctx) as s:
            run = await s.get(Run, uuid.UUID(run_id))
            if run is None or run.source_id is None:
                raise permanent("not_found", "run or source missing")
            source = await s.get(Source, run.source_id)
            if source is None:
                raise permanent("not_found", "source no longer exists")
            run.status, run.started_at = "running", run.started_at or datetime.now(UTC)
            source.status, source.last_run_id = "syncing", run.id
            connector_name, config = source.connector, dict(source.config)
        connector = self.d.registry.get(PluginKind.CONNECTOR, connector_name)
        context = self._context(scope, run_id)
        items: list[ItemRef] = []
        try:
            async for item in connector.discover(context, config):
                items.append(
                    ItemRef(
                        item.uri,
                        item.title,
                        item.version,
                        item.media_type,
                        item.size,
                        dict(item.metadata),
                    )
                )
                if len(items) >= context.max_items:
                    break
        except (FetchBlocked, MissingCredentials, PermissionError) as exc:
            raise permanent("discovery_refused", str(exc)) from exc
        except (FetchFailed, OSError, RuntimeError) as exc:
            raise ApplicationError(f"discovery failed: {exc}", type="DiscoveryFailed") from exc
        async with self.d.db.session(ctx) as s:
            run = await s.get(Run, uuid.UUID(run_id))
            assert run is not None
            run.discovered = len(items)
            run.truncated = len(items) >= context.max_items
            run.warnings = [{"uri": u, "message": m} for u, m in context.warnings[:MAX_WARNINGS]]
        return Discovery(run_id, items)

    @activity.defn(name="ingestion.fetch_item")
    async def fetch_item(self, scope: TenantScope, run_id: str, item: ItemRef) -> FetchOutcome:
        ctx = self._ctx(scope)
        async with self.d.db.session(ctx) as s:
            run = await s.get(Run, uuid.UUID(run_id))
            assert run is not None
            assert run.source_id is not None
            source = await s.get(Source, run.source_id)
            assert source is not None
            doc = await s.scalar(
                select(Document).where(Document.source_id == source.id, Document.uri == item.uri)
            )
            if doc is None:
                doc = Document(
                    tenant_id=ctx.tenant_id,
                    collection_id=source.collection_id,
                    source_id=source.id,
                    uri=item.uri,
                    title=item.title,
                )
                s.add(doc)
                await s.flush()
            doc.last_seen_run_id = run.id
            doc_id, ready = doc.id, doc.status == "ready"
            if ready and item.version and item.version == doc.source_version:
                await self._bump(s, run_id, unchanged=1)
                return FetchOutcome(str(doc_id), False)
            previous = doc.source_version if ready else None
            connector_name, config, known_hash = (
                source.connector,
                dict(source.config),
                doc.content_hash,
            )
        connector = self.d.registry.get(PluginKind.CONNECTOR, connector_name)
        item_obj = Item(
            item.uri, item.title, item.version, item.media_type, item.size, item.metadata
        )
        try:
            content = await connector.fetch(
                self._context(scope, run_id), config, item_obj, previous
            )
            if len(content.data) > self.d.settings.fetch.max_bytes:
                raise FetchTooLarge("content too large")
        except (
            FetchBlocked,
            FetchTooLarge,
            MissingCredentials,
            PermissionError,
            ValueError,
            BlobNotFound,
        ) as exc:
            code = {
                FetchBlocked: "fetch_blocked",
                FetchTooLarge: "too_large",
                MissingCredentials: "credentials_missing",
            }.get(type(exc), "fetch_failed")
            async with self.d.db.session(ctx) as s:
                doc = await s.get(Document, doc_id)
                assert doc is not None
                await self._fail(s, ctx, doc, run_id, code, str(exc))
            return FetchOutcome(str(doc_id), False)
        except (FetchFailed, OSError, RuntimeError, NexiqonError) as exc:
            raise ApplicationError(f"fetch failed: {exc}", type="FetchFailed") from exc
        async with self.d.db.session(ctx) as s:
            doc = await s.get(Document, doc_id)
            assert doc is not None
            if content.not_modified:
                await self._bump(s, run_id, unchanged=1)
                return FetchOutcome(str(doc_id), False)
            digest = hashlib.sha256(content.data).hexdigest()
            if ready and digest == known_hash:
                doc.source_version = content.version or item.version
                await self._bump(s, run_id, unchanged=1)
                return FetchOutcome(str(doc_id), False)
            doc.version += 1
            key = tenant_key(ctx.tenant_id, "documents", str(doc.id), f"v{doc.version}")
            await self.d.blobs.put(key, content.data, content.media_type)
            old_key = doc.blob_key
            doc.blob_key, doc.content_hash, doc.size = key, digest, len(content.data)
            doc.media_type = content.media_type
            doc.source_version = content.version or item.version
            doc.status, doc.error_code, doc.error_detail = "pending", None, None
        if old_key and old_key != key:
            await self.d.blobs.delete(old_key)
        return FetchOutcome(str(doc_id), True)

    @activity.defn(name="ingestion.scan")
    async def scan(self, scope: TenantScope, run_id: str, document_id: str) -> bool:
        """Malware scan (IN-05). Infected files are quarantined and never parsed."""
        ctx = self._ctx(scope)
        async with self.d.db.session(ctx) as s:
            doc = await s.get(Document, uuid.UUID(document_id))
            if doc is None or doc.blob_key is None:
                raise permanent("not_found", "document missing")
            key = doc.blob_key
        data = await self.d.blobs.get(key)
        try:
            result = await self.d.scanner.scan(data)
        except ScanUnavailable as exc:
            raise ApplicationError(str(exc), type="ScanUnavailable") from exc
        async with self.d.db.session(ctx) as s:
            doc = await s.get(Document, uuid.UUID(document_id))
            assert doc is not None
            doc.scanner = result.scanner
            if result.clean:
                return True
            quarantine = tenant_key(ctx.tenant_id, "quarantine", document_id, f"v{doc.version}")
            await self.d.blobs.put(quarantine, data, "application/octet-stream")
            doc.status, doc.scan_signature, doc.blob_key = (
                "quarantined",
                result.signature,
                quarantine,
            )
            doc.error_code, doc.error_detail = (
                "malware_detected",
                f"Malware signature: {result.signature}",
            )
            await self._bump(s, run_id, quarantined=1)
            self._event(
                s,
                ctx,
                "document.quarantined",
                document_id,
                {"document_id": document_id, "signature": result.signature},
            )
        await self.d.blobs.delete(key)
        if doc.indexed_version is not None:  # an older clean version must not stay searchable
            await self.d.index.delete_document(ctx.tenant_id, uuid.UUID(document_id))
        return False

    @activity.defn(name="ingestion.process")
    async def process(self, scope: TenantScope, run_id: str, document_id: str) -> int:
        """Parse, build the tree, embed chunks and replace the document in the index."""
        ctx = self._ctx(scope)
        async with self.d.db.session(ctx) as s:
            doc = await s.get(Document, uuid.UUID(document_id))
            if doc is None or doc.blob_key is None or doc.status in ("deleted", "quarantined"):
                return 0
            collection = await s.get(Collection, doc.collection_id)
            assert collection is not None
            doc.status = "processing"
            snapshot: dict[str, Any] = {
                "blob_key": doc.blob_key,
                "media_type": doc.media_type or "",
                "uri": doc.uri,
                "title": doc.title,
                "version": doc.version,
                "collection_id": collection.id,
                "model_profile": collection.model_profile,
                "retrieval_profile": collection.retrieval_profile,
                "classification": collection.classification,
                "acl_groups": list(collection.acl_groups),
                "embedding_model": collection.embedding_model,
            }
        try:
            nodes, title, model = await self._build(scope, ctx, document_id, snapshot)
        except PermanentError as exc:
            async with self.d.db.session(ctx) as s:
                doc = await s.get(Document, uuid.UUID(document_id))
                assert doc is not None
                await self._fail(s, ctx, doc, run_id, exc.code, exc.detail)
            return 0
        except TransientError as exc:
            raise ApplicationError(str(exc), type="Transient") from exc
        chunks = [n for n in nodes if n.kind == "chunk"]
        async with self.d.db.session(ctx) as s:
            doc = await s.get(Document, uuid.UUID(document_id))
            collection = await s.get(Collection, uuid.UUID(str(snapshot["collection_id"])))
            assert doc is not None
            assert collection is not None
            if collection.embedding_model is None:
                collection.embedding_model = model
            doc.status, doc.error_code, doc.error_detail = "ready", None, None
            doc.title = title
            doc.indexed_version, doc.indexed_at = int(snapshot["version"]), datetime.now(UTC)
            doc.chunk_count, doc.token_count = len(chunks), sum(n.token_count for n in chunks)
            doc.section_count = sum(1 for n in nodes if n.kind == "section")
            await self._bump(s, run_id, processed=1)
            self._event(
                s,
                ctx,
                "document.indexed",
                document_id,
                {
                    "document_id": document_id,
                    "collection_id": str(collection.id),
                    "version": doc.version,
                    "chunks": len(chunks),
                },
            )
        return len(chunks)

    async def _build(
        self, scope: TenantScope, ctx: TenantContext, document_id: str, snap: dict[str, Any]
    ) -> tuple[list[Any], str | None, str]:
        tenant = ctx.tenant_id
        parser = self.d.registry.parser_for(str(snap["media_type"]), str(snap["uri"]))
        if parser is None:
            raise PermanentError(
                "unsupported_type",
                f"No parser for {snap['media_type'] or 'unknown type'} ({snap['uri']})",
            )
        data = await self.d.blobs.get(str(snap["blob_key"]))
        try:
            parsed = parser.parse(data, str(snap["media_type"]), str(snap["uri"]))
        except Exception as exc:
            raise PermanentError("parse_failed", f"{parser.manifest.title}: {exc}") from exc
        try:
            profile = await self.d.retrieval_profiles.get(
                str(tenant), self.d.tokens.for_tenant(tenant), str(snap["retrieval_profile"])
            )
        except NexiqonError as exc:
            if exc.status >= 500:
                raise TransientError(str(exc)) from exc
            raise PermanentError("profile_unavailable", str(exc.detail or exc)) from exc
        chunking = {**DEFAULT_CHUNKING, **(profile.get("chunking") or {})}
        strategy = str(chunking.pop("strategy")).replace("_", "-")
        try:
            chunker = self.d.registry.get(PluginKind.CHUNKER, strategy)
        except Exception as exc:
            raise PermanentError(
                "profile_unavailable", f"Unknown chunking strategy {strategy!r}"
            ) from exc
        fallback = str(snap["title"] or Path(str(snap["uri"]).split("?")[0]).name or "Untitled")
        nodes = build_tree(
            uuid.UUID(document_id), int(snap["version"]), parsed, chunker, chunking, fallback
        )
        chunks = [n for n in nodes if n.kind == "chunk"]
        if not chunks:
            raise PermanentError(
                "empty_document", "No text could be extracted (scanned images need OCR)"
            )
        title = nodes[0].title
        vectors: list[list[float]] = []
        model = ""
        batch = self.d.settings.embed_batch_size
        for i in range(0, len(chunks), batch):
            texts = [embedding_text(title, n) for n in chunks[i : i + batch]]
            got, model = await self.d.embedder.embed(
                tenant, str(snap["model_profile"]), str(snap["classification"]), texts
            )
            vectors.extend(got)
        expected = snap["embedding_model"]
        if expected and expected != model:
            raise PermanentError(
                "embedding_model_changed",
                f"Collection uses {expected}; the profile now returns {model}. Reindex the collection.",
            )
        by_id = {n.id: v for n, v in zip(chunks, vectors, strict=True)}
        payload = {
            "collection_id": str(snap["collection_id"]),
            "version": int(snap["version"]),
            "title": title,
            "source_uri": snap["uri"],
            "acl_groups": snap["acl_groups"],
            "classification": snap["classification"],
            "embedding_model": model,
            "nodes": [
                {
                    "id": str(n.id),
                    "parent_id": str(n.parent_id) if n.parent_id else None,
                    "path": n.path,
                    "kind": n.kind,
                    "ordinal": n.ordinal,
                    "title": n.title,
                    "heading_path": n.heading_path,
                    "text": n.text,
                    "page_start": n.page_start,
                    "page_end": n.page_end,
                    "token_count": n.token_count,
                    "embedding": by_id.get(n.id),
                }
                for n in nodes
            ],
        }
        await self.d.index.put_document(tenant, uuid.UUID(document_id), payload)
        return nodes, title, model

    @activity.defn(name="ingestion.mark_failed")
    async def mark_failed(
        self, scope: TenantScope, run_id: str, document_id: str, code: str, detail: str
    ) -> None:
        ctx = self._ctx(scope)
        async with self.d.db.session(ctx) as s:
            doc = await s.get(Document, uuid.UUID(document_id))
            if doc is not None and doc.status not in ("deleted", "quarantined"):
                await self._fail(s, ctx, doc, run_id, code, detail)

    @activity.defn(name="ingestion.list_documents")
    async def list_documents(self, scope: TenantScope, run_id: str) -> list[str]:
        """Documents to reprocess in a reindex run (every non-deleted document with content)."""
        ctx = self._ctx(scope)
        async with self.d.db.session(ctx) as s:
            run = await s.get(Run, uuid.UUID(run_id))
            assert run is not None
            run.status, run.started_at = "running", datetime.now(UTC)
            ids = (
                await s.scalars(
                    select(Document.id).where(
                        Document.collection_id == run.collection_id,
                        Document.status.in_(("ready", "failed", "pending")),
                        Document.blob_key.is_not(None),
                    )
                )
            ).all()
            run.discovered = len(ids)
        return [str(i) for i in ids]

    @activity.defn(name="ingestion.finish_run")
    async def finish_run(self, scope: TenantScope, run_id: str, error: str | None) -> None:
        """Close the run. A complete sync deletes documents the source no longer has (IN-07)."""
        ctx = self._ctx(scope)
        async with self.d.db.session(ctx) as s:
            run = await s.get(Run, uuid.UUID(run_id))
            assert run is not None
            stale: list[uuid.UUID] = []
            if (
                run.kind == "sync"
                and error is None
                and not run.truncated
                and run.source_id is not None
            ):
                stale = list(
                    (
                        await s.scalars(
                            select(Document.id).where(
                                Document.source_id == run.source_id,
                                Document.status != "deleted",
                                (Document.last_seen_run_id != run.id)
                                | Document.last_seen_run_id.is_(None),
                            )
                        )
                    ).all()
                )
        for doc_id in stale:
            await self.delete_document(ctx, doc_id)
        async with self.d.db.session(ctx) as s:
            run = await s.get(Run, uuid.UUID(run_id))
            assert run is not None
            run.deleted += len(stale)
            run.status = "failed" if error else "completed"
            run.error, run.finished_at = error, datetime.now(UTC)
            if run.source_id is not None:
                await s.execute(
                    update(Source)
                    .where(Source.id == run.source_id)
                    .values(
                        status="idle",
                        last_synced_at=run.finished_at if not error else Source.last_synced_at,
                    )
                )
            counters = {
                k: getattr(run, k)
                for k in (
                    "discovered",
                    "processed",
                    "unchanged",
                    "failed",
                    "quarantined",
                    "deleted",
                )
            }
            self._event(
                s,
                ctx,
                "run.completed",
                run_id,
                {"run_id": run_id, "status": run.status, **counters},
            )
        shutil.rmtree(self.d.settings.scratch_dir / str(ctx.tenant_id) / run_id, ignore_errors=True)

    # ------------------------------------------------------------------ deletion (also used by the API)

    async def delete_document(self, ctx: TenantContext, document_id: uuid.UUID) -> None:
        """Index first, then the file, then the record: content is unretrievable before we report."""
        tenant = ctx.tenant_id
        async with self.d.db.session(ctx) as s:
            doc = await s.get(Document, document_id)
            if doc is None or doc.status == "deleted":
                return
            key = doc.blob_key
        await self.d.index.delete_document(tenant, document_id)
        if key:
            await self.d.blobs.delete(key)
        async with self.d.db.session(ctx) as s:
            doc = await s.get(Document, document_id)
            assert doc is not None
            doc.status, doc.blob_key, doc.indexed_version = "deleted", None, None
            doc.chunk_count = doc.section_count = doc.token_count = 0
            self._event(
                s,
                ctx,
                "document.deleted",
                str(document_id),
                {"document_id": str(document_id), "collection_id": str(doc.collection_id)},
            )

    def activities(self) -> list[Callable[..., Any]]:
        return [
            self.start_run,
            self.discover,
            self.fetch_item,
            self.scan,
            self.process,
            self.mark_failed,
            self.list_documents,
            self.finish_run,
        ]
