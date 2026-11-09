"""Vector-store port (RT-01). Adapter: adapters/pgvector.py.

Every query takes :class:`Filters`, which the adapter must apply *inside* the index scan (filter
before rank): a restricted chunk can never take a top-k slot, let alone be returned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


def strictest(*levels: str) -> str:
    """The most sensitive of the given classifications (unknown labels count as restricted)."""
    rank = {c: i for i, c in enumerate(CLASSIFICATIONS)}
    return max(levels, key=lambda c: rank.get(c, len(CLASSIFICATIONS))) if levels else "internal"


@dataclass(frozen=True)
class Filters:
    collection_ids: list[uuid.UUID]
    classifications: list[str] = field(default_factory=lambda: list(CLASSIFICATIONS))
    # None: no access-group restriction (bypass roles). Otherwise: nodes with no groups, or any
    # group the caller has.
    groups: list[str] | None = field(default_factory=list)


@dataclass
class Hit:
    id: uuid.UUID
    document_id: uuid.UUID
    collection_id: uuid.UUID
    parent_id: uuid.UUID | None
    path: str
    text: str
    heading_path: list[str]
    token_count: int
    page_start: int | None
    page_end: int | None
    source_uri: str | None
    score: float  # cosine similarity (vector) or ts_rank_cd (keyword)
    classification: str = "internal"  # from the index, never from the request


@dataclass
class Node:
    id: uuid.UUID
    document_id: uuid.UUID
    parent_id: uuid.UUID | None
    kind: str
    path: str
    title: str | None
    text: str
    heading_path: list[str]
    token_count: int
    page_start: int | None
    page_end: int | None
    source_uri: str | None
    collection_id: uuid.UUID
    classification: str = "internal"


class VectorStore(Protocol):
    #: Capability flags, e.g. "filter_before_rank" (required), "keyword", "tree".
    capabilities: frozenset[str]

    async def vector_search(
        self, tenant: uuid.UUID, vector: list[float], model: str, filters: Filters, limit: int
    ) -> list[Hit]: ...

    async def keyword_search(
        self, tenant: uuid.UUID, terms: list[str], filters: Filters, limit: int
    ) -> list[Hit]: ...

    async def chunk_children(
        self, tenant: uuid.UUID, parent_ids: list[uuid.UUID], filters: Filters
    ) -> dict[uuid.UUID, list[Node]]: ...

    async def nodes(
        self, tenant: uuid.UUID, ids: list[uuid.UUID], filters: Filters
    ) -> list[Node]: ...

    async def document_titles(
        self, tenant: uuid.UUID, document_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]: ...
