"""PostgreSQL + pgvector adapter for the vector-store port.

Filters are SQL predicates in the same statement as the HNSW scan, with pgvector's iterative index
scan so filtered queries still return ``limit`` rows (filter before rank). RLS adds the tenant.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import Select, func, literal_column, or_, select, text
from sqlalchemy.sql.elements import ColumnClause

from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.tenancy import TenantContext
from nexiqon_retrieval.models import IndexNode
from nexiqon_retrieval.store import Filters, Hit, Node

N = IndexNode
TSV: ColumnClause[Any] = literal_column("retrieval.index_nodes.tsv")
_COLUMNS = (
    N.id,
    N.document_id,
    N.collection_id,
    N.parent_id,
    N.path,
    N.text,
    N.heading_path,
    N.token_count,
    N.page_start,
    N.page_end,
    N.source_uri,
)


def _ctx(tenant: uuid.UUID) -> TenantContext:
    return TenantContext(tenant_id=tenant, actor_id="service:retrieval", actor_type="service")


def _filtered(query: Select[Any], filters: Filters) -> Select[Any]:
    query = query.where(
        N.collection_id.in_(filters.collection_ids), N.classification.in_(filters.classifications)
    )
    if filters.groups is not None:
        query = query.where(
            or_(func.cardinality(N.acl_groups) == 0, N.acl_groups.overlap(filters.groups))
        )
    return query


def _hit(row: Any, score: float) -> Hit:
    return Hit(
        id=row.id,
        document_id=row.document_id,
        collection_id=row.collection_id,
        parent_id=row.parent_id,
        path=row.path,
        text=row.text,
        heading_path=list(row.heading_path),
        token_count=row.token_count,
        page_start=row.page_start,
        page_end=row.page_end,
        source_uri=row.source_uri,
        score=float(score),
    )


def _node(n: IndexNode) -> Node:
    return Node(
        id=n.id,
        document_id=n.document_id,
        parent_id=n.parent_id,
        kind=n.kind,
        path=n.path,
        title=n.title,
        text=n.text,
        heading_path=list(n.heading_path),
        token_count=n.token_count,
        page_start=n.page_start,
        page_end=n.page_end,
        source_uri=n.source_uri,
        collection_id=n.collection_id,
    )


class PgVectorStore:
    capabilities = frozenset({"filter_before_rank", "keyword", "tree"})

    def __init__(self, db: TenantSessionFactory, ef_search: int = 100) -> None:
        self.db = db
        self.ef_search = int(ef_search)

    async def vector_search(
        self, tenant: uuid.UUID, vector: list[float], model: str, filters: Filters, limit: int
    ) -> list[Hit]:
        distance = N.embedding.cosine_distance(vector).label("distance")
        query = _filtered(
            cast(Select[Any], select(*_COLUMNS, distance)).where(
                N.kind == "chunk", N.embedding_model == model
            ),
            filters,
        )
        async with self.db.session(_ctx(tenant)) as s:
            # Keep scanning the HNSW graph until `limit` rows pass the filters (pgvector >= 0.8).
            await s.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            await s.execute(text(f"SET LOCAL hnsw.ef_search = {max(self.ef_search, limit)}"))
            rows = (await s.execute(query.order_by(distance).limit(limit))).all()
        hits = [_hit(r, 1.0 - float(r.distance)) for r in rows]
        hits.sort(key=lambda h: h.score, reverse=True)  # relaxed order: re-sort exactly
        return hits

    async def keyword_search(
        self, tenant: uuid.UUID, terms: list[str], filters: Filters, limit: int
    ) -> list[Hit]:
        if not terms:
            return []
        tsquery = func.to_tsquery(
            literal_column("'simple'::regconfig"), " | ".join(f"'{t}'" for t in terms)
        )
        rank = func.ts_rank_cd(TSV, tsquery, 32).label("rank")
        query = _filtered(
            cast(Select[Any], select(*_COLUMNS, rank)).where(
                N.kind == "chunk", TSV.op("@@")(tsquery)
            ),
            filters,
        )
        async with self.db.session(_ctx(tenant)) as s:
            rows = (await s.execute(query.order_by(rank.desc()).limit(limit))).all()
        return [_hit(r, float(r.rank)) for r in rows]

    async def chunk_children(
        self, tenant: uuid.UUID, parent_ids: list[uuid.UUID], filters: Filters
    ) -> dict[uuid.UUID, list[Node]]:
        if not parent_ids:
            return {}
        query = _filtered(select(N).where(N.kind == "chunk", N.parent_id.in_(parent_ids)), filters)
        async with self.db.session(_ctx(tenant)) as s:
            rows = (await s.scalars(query.order_by(N.path))).all()
        out: dict[uuid.UUID, list[Node]] = {}
        for r in rows:
            assert r.parent_id is not None
            out.setdefault(r.parent_id, []).append(_node(r))
        return out

    async def nodes(self, tenant: uuid.UUID, ids: list[uuid.UUID], filters: Filters) -> list[Node]:
        if not ids:
            return []
        async with self.db.session(_ctx(tenant)) as s:
            rows = (await s.scalars(_filtered(select(N).where(N.id.in_(ids)), filters))).all()
        return [_node(r) for r in rows]

    async def document_titles(
        self, tenant: uuid.UUID, document_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        if not document_ids:
            return {}
        async with self.db.session(_ctx(tenant)) as s:
            rows = (
                await s.execute(
                    select(N.document_id, N.title).where(
                        N.kind == "document", N.document_id.in_(document_ids)
                    )
                )
            ).all()
        return {r.document_id: r.title for r in rows}
