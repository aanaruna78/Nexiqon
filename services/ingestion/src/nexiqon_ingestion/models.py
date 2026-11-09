"""Ingestion data (schema ``ingestion``): collections, sources, documents, runs, outbox.

Raw files live in object storage (``blob_key``); the searchable tree lives in the retrieval index.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexiqon_core.db import TenantScopedMixin, service_metadata
from nexiqon_core.events import OutboxMixin

SCHEMA = "ingestion"
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class Collection(TenantScopedMixin, Base):
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    name: Mapped[str] = mapped_column(String(63))
    description: Mapped[str] = mapped_column(String(500), default="")
    model_profile: Mapped[str] = mapped_column(String(63), default="cloud-frontier")
    retrieval_profile: Mapped[str] = mapped_column(String(63), default="standard")
    classification: Mapped[str] = mapped_column(String(16), default="internal")
    # Empty: every member of the workspace may retrieve from this collection.
    acl_groups: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    # The embedding model all indexed chunks use; cleared while a reindex switches models.
    embedding_model: Mapped[str | None] = mapped_column(String(200), default=None)
    created_by: Mapped[str] = mapped_column(String(200))


class Source(TenantScopedMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("collection_id", "name"),)

    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.collections.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(63))
    connector: Mapped[str] = mapped_column(String(63))
    config: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    schedule_hours: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[str] = mapped_column(String(16), default="idle")  # idle | syncing
    last_run_id: Mapped[UUID | None] = mapped_column(default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_by: Mapped[str] = mapped_column(String(200))


class Document(TenantScopedMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_id", "uri"),)

    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.collections.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.sources.id", ondelete="CASCADE"), index=True
    )
    uri: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str | None] = mapped_column(String(1000), default=None)
    media_type: Mapped[str | None] = mapped_column(String(200), default=None)
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    source_version: Mapped[str | None] = mapped_column(String(200), default=None)
    version: Mapped[int] = mapped_column(Integer, default=0)
    indexed_version: Mapped[int | None] = mapped_column(Integer, default=None)
    blob_key: Mapped[str | None] = mapped_column(String(1000), default=None)
    # pending | processing | ready | failed | quarantined | deleted
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), default=None)
    error_detail: Mapped[str | None] = mapped_column(String(1000), default=None)
    scanner: Mapped[str | None] = mapped_column(String(32), default=None)
    scan_signature: Mapped[str | None] = mapped_column(String(200), default=None)
    section_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_run_id: Mapped[UUID | None] = mapped_column(default=None)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Run(TenantScopedMixin, Base):
    """One sync, upload or reindex; counters drive Studio's live progress."""

    __tablename__ = "runs"

    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.collections.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[UUID | None] = mapped_column(default=None, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # sync | upload | reindex
    status: Mapped[str] = mapped_column(
        String(16), default="queued"
    )  # queued|running|completed|failed
    workflow_id: Mapped[str | None] = mapped_column(String(300), default=None)
    discovered: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    quarantined: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(default=False)
    # Discovery could not see the whole source; nothing may be deleted on this run's evidence.
    incomplete: Mapped[bool] = mapped_column(default=False)
    warnings: Mapped[list[dict[str, str]]] = mapped_column(_JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_by: Mapped[str] = mapped_column(String(200))


class Outbox(OutboxMixin, Base):
    __tablename__ = "outbox_events"
