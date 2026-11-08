"""Retrieval search fixtures: real config (profiles) and Postgres, offline hash embeddings."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexiqon_config.main import create_app as create_config_app
from nexiqon_config.settings import ServiceSettings as ConfigSettings
from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair
from nexiqon_ingestion.plugins.chunkers import HeadingAwareChunker
from nexiqon_ingestion.plugins.parsers import MarkdownParser
from nexiqon_ingestion.tree import build_tree, embedding_text
from nexiqon_retrieval.main import create_app
from nexiqon_retrieval.settings import ServiceSettings
from nexiqon_retrieval.testing import MODEL, HashModelClient, hash_embed

ROLES = {
    "owner": ["**"],
    "admin": ["**"],
    "member": ["**.read", "config.profiles.resolve", "retrieval.search.*"],
    "end_user": ["config.profiles.resolve", "retrieval.search.*", "model.inference.run"],
    "service:ingestion": [
        "retrieval.index.write",
        "retrieval.index.read",
        "config.profiles.resolve",
    ],
}


@pytest.fixture(scope="session")
def search_db(postgres: PgUrls) -> PgUrls:
    upgrade("config", postgres.owner, postgres.app_role)
    upgrade("retrieval", postgres.owner, postgres.app_role)
    return postgres


@dataclass
class SearchStack:
    client: TestClient
    tenants: TwoTenants
    service: ServiceTokens
    models: HashModelClient
    collection: uuid.UUID = field(default_factory=uuid.uuid4)

    def headers(
        self,
        roles: set[str],
        groups: set[str] | None = None,
        actor_type: str = "user",
        tenant: str = "a",
    ) -> dict[str, str]:
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        ctx = TenantContext(
            t, f"{actor_type}-1", actor_type, frozenset(roles), frozenset(groups or set())
        )  # type: ignore[arg-type]
        return {CONTEXT_HEADER: self.tenants.issuer.issue(ctx)}

    def index(
        self,
        markdown: str,
        uri: str,
        *,
        acl: list[str] | None = None,
        classification: str = "internal",
        model: str = MODEL,
        collection: uuid.UUID | None = None,
        tenant: str = "a",
        max_tokens: int = 400,
        pages: bool = False,
    ) -> uuid.UUID:
        """Parse and chunk with ingestion's real plugins, embed offline, write to the index."""
        document_id = uuid.uuid4()
        parsed = MarkdownParser().parse(markdown.encode(), "text/markdown", uri)
        nodes = build_tree(
            document_id,
            1,
            parsed,
            HeadingAwareChunker(),
            {"max_tokens": max_tokens, "overlap_tokens": 0},
            uri,
        )
        title = nodes[0].title
        body: dict[str, Any] = {
            "collection_id": str(collection or self.collection),
            "version": 1,
            "title": title,
            "source_uri": uri,
            "acl_groups": acl or [],
            "classification": classification,
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
                    "page_start": (i + 1 if pages else None) if n.kind == "chunk" else None,
                    "page_end": (i + 1 if pages else None) if n.kind == "chunk" else None,
                    "token_count": n.token_count,
                    "embedding": hash_embed(embedding_text(title, n))
                    if n.kind == "chunk"
                    else None,
                }
                for i, n in enumerate(nodes)
            ],
        }
        t = (self.tenants.a if tenant == "a" else self.tenants.b).context.tenant_id
        r = self.client.put(
            f"/v1/index/documents/{document_id}",
            json=body,
            headers={CONTEXT_HEADER: self.service.for_tenant(t)},
        )
        assert r.status_code == 200, r.text
        return document_id

    def search(
        self, query: str, headers: dict[str, str] | None = None, **extra: Any
    ) -> dict[str, Any]:
        body = {"query": query, "collection_ids": [str(self.collection)], **extra}
        r = self.client.post("/v1/search", json=body, headers=headers or self.headers({"member"}))
        assert r.status_code == 200, r.text
        out: dict[str, Any] = r.json()
        return out


@pytest.fixture
def stack(search_db: PgUrls) -> Iterator[SearchStack]:
    tenants = TwoTenants.create(roles=frozenset({"member"}))
    private, public = make_keypair()
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc": public},
        service_keys={"svc": "ingestion"},
    )
    service = ServiceTokens(
        "ingestion", tokens, ServiceIdentitySettings(key_id="svc", private_key=private)
    )  # type: ignore[arg-type]
    authorizer = StaticAuthorizer(ROLES)
    db = DatabaseSettings(url=search_db.app)
    config_app = create_config_app(
        ConfigSettings(log_json=False, context_token=tokens, database=db), authorizer=authorizer
    )
    models = HashModelClient()
    app = create_app(
        ServiceSettings(
            log_json=False, context_token=tokens, database=db, config_url="http://config"
        ),
        authorizer=authorizer,
        models=models,
        service_transport=httpx.ASGITransport(app=config_app),
    )
    with TestClient(app) as client:
        yield SearchStack(client, tenants, service, models)
