"""Vector-store port contract (RT-01): every adapter must pass these. Adapter today: pgvector."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_retrieval.adapters.pgvector import PgVectorStore
from nexiqon_retrieval.store import Filters
from nexiqon_retrieval.testing import hash_embed

from .conftest import SearchStack

pytestmark = pytest.mark.integration


def _run(stack: SearchStack, url: str, fn: Any) -> Any:
    async def go() -> Any:
        engine = create_engine(url)
        try:
            return await fn(PgVectorStore(TenantSessionFactory(engine), ef_search=40))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_filter_is_applied_before_ranking(stack: SearchStack, search_db: Any) -> None:
    # 300 restricted near-duplicates of the query crowd the nearest neighbours; one visible chunk
    # is far away. A post-filtering store would return nothing; filter-before-rank returns it.
    near = "\n\n".join(f"## Secret {i}\n\nquarterly salary bands table {i}" for i in range(300))
    stack.index(f"# Restricted\n\n{near}", "upload://restricted.md", acl=["hr"], max_tokens=20)
    stack.index("# Public\n\n## Weather\n\nsunny skies over the harbour", "upload://public.md")
    tenant = stack.tenants.a.context.tenant_id
    vector = hash_embed("quarterly salary bands table")
    hits = _run(
        stack,
        search_db.app,
        lambda store: store.vector_search(
            tenant, vector, "hash-ngram-1024", Filters([stack.collection], groups=["sales"]), 5
        ),
    )
    assert [h.source_uri for h in hits] == ["upload://public.md"]
    allowed = _run(
        stack,
        search_db.app,
        lambda store: store.vector_search(
            tenant, vector, "hash-ngram-1024", Filters([stack.collection], groups=["hr"]), 5
        ),
    )
    assert len(allowed) == 5
    assert all(h.source_uri == "upload://restricted.md" for h in allowed)
    assert allowed == sorted(allowed, key=lambda h: h.score, reverse=True)


def test_collection_classification_and_tenant_scoping(stack: SearchStack, search_db: Any) -> None:
    other = uuid.uuid4()
    stack.index(
        "# A\n\n## S\n\nalpha beta gamma",
        "upload://a.md",
        collection=other,
        classification="restricted",
    )
    tenant = stack.tenants.a.context.tenant_id
    vector = hash_embed("alpha beta gamma")
    assert (
        _run(
            stack,
            search_db.app,
            lambda s: s.vector_search(
                tenant, vector, "hash-ngram-1024", Filters([stack.collection]), 5
            ),
        )
        == []
    )
    only_internal = Filters([other], classifications=["public", "internal"])
    assert (
        _run(stack, search_db.app, lambda s: s.keyword_search(tenant, ["alpha"], only_internal, 5))
        == []
    )
    assert (
        len(
            _run(
                stack,
                search_db.app,
                lambda s: s.keyword_search(tenant, ["alpha"], Filters([other]), 5),
            )
        )
        == 1
    )
    tenant_b = stack.tenants.b.context.tenant_id
    assert (
        _run(
            stack,
            search_db.app,
            lambda s: s.keyword_search(tenant_b, ["alpha"], Filters([other]), 5),
        )
        == []
    )
    assert "filter_before_rank" in PgVectorStore.capabilities
