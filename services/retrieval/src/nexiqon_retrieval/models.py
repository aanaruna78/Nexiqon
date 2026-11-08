"""Retrieval index (schema ``retrieval``): the document tree with vectors and keyword index.

One row per node: document > section > ... > chunk (``parent_id`` + ``ltree`` path, ARCHITECTURE
§5.3). Chunks carry 1024-d embeddings; ``tsv`` (generated, in the migration) serves keyword search.
Written only by the ingestion service through the index API; read by search (slice 3).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from nexiqon_core.db import TenantScopedMixin, service_metadata

SCHEMA = "retrieval"
DIMENSIONS = 1024


class Ltree(UserDefinedType[str]):
    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "ltree"


class Base(DeclarativeBase):
    metadata = service_metadata(SCHEMA)


class IndexNode(TenantScopedMixin, Base):
    __tablename__ = "index_nodes"

    collection_id: Mapped[UUID] = mapped_column(index=True)
    document_id: Mapped[UUID] = mapped_column(index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[UUID | None] = mapped_column(default=None)
    path: Mapped[str] = mapped_column(Ltree())
    kind: Mapped[str] = mapped_column(String(16))  # document | section | chunk | summary
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(String(1000), default=None)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(String(1000)), default=list)
    heading_text: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    page_start: Mapped[int | None] = mapped_column(Integer, default=None)
    page_end: Mapped[int | None] = mapped_column(Integer, default=None)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    source_uri: Mapped[str | None] = mapped_column(String(2000), default=None)
    acl_groups: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    classification: Mapped[str] = mapped_column(String(16), default="internal")
    embedding_model: Mapped[str | None] = mapped_column(String(200), default=None)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIMENSIONS), default=None)
