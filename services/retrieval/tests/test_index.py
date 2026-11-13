"""Retrieval index API: tree validation, atomic replace, stale-version guard, isolation, lifecycle."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexiqon_core.authz import StaticAuthorizer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.migrations import upgrade
from nexiqon_core.pytest_plugin import PgUrls
from nexiqon_core.service_auth import ServiceTokens
from nexiqon_core.settings import ContextTokenSettings, DatabaseSettings, ServiceIdentitySettings
from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext
from nexiqon_core.testing import TwoTenants, make_keypair
from nexiqon_retrieval.lifecycle import IndexLifecycle
from nexiqon_retrieval.main import create_app
from nexiqon_retrieval.settings import ServiceSettings

pytestmark = pytest.mark.integration
ROLES = {
    "service:ingestion": ["retrieval.index.write", "retrieval.index.read"],
    "member": ["**.read"],
}


@pytest.fixture(scope="session")
def retrieval_db(postgres: PgUrls) -> PgUrls:
    upgrade("retrieval", postgres.owner, postgres.app_role)
    return postgres


@dataclass
class Setup:
    """Tenant A/B headers carry ingestion's service token; ``member`` is a user of tenant A."""

    client: TestClient
    tenants: TwoTenants
    a: dict[str, str]
    b: dict[str, str]
    member: dict[str, str]
    staff: dict[str, str]  # a member of the documents' access group


@pytest.fixture
def setup(retrieval_db: PgUrls) -> Iterator[Setup]:
    tenants = TwoTenants.create(roles=frozenset({"member"}))
    private, public = make_keypair()
    tokens = ContextTokenSettings(
        public_keys={**tenants.settings.public_keys, "svc": public},
        service_keys={"svc": "ingestion"},
    )
    svc = ServiceTokens(
        "ingestion", tokens, ServiceIdentitySettings(key_id="svc", private_key=private)
    )  # type: ignore[arg-type]
    app = create_app(
        ServiceSettings(
            log_json=False,
            context_token=tokens,
            database=DatabaseSettings(url=retrieval_db.app, pool_size=0),
        ),
        authorizer=StaticAuthorizer(ROLES),
    )
    header = CONTEXT_HEADER
    with TestClient(app) as client:
        yield Setup(
            client,
            tenants,
            {header: svc.for_tenant(tenants.a.context.tenant_id)},
            {header: svc.for_tenant(tenants.b.context.tenant_id)},
            tenants.a.headers,
            {
                header: tenants.issuer.issue(
                    TenantContext(
                        tenants.a.context.tenant_id,
                        "u-staff",
                        "user",
                        frozenset({"member"}),
                        frozenset({"staff"}),
                    )
                )
            },
        )


def vec(x: float) -> list[float]:
    return [x] * 1024


def doc(collection: uuid.UUID, version: int = 1, **over: Any) -> dict[str, Any]:
    root, sec, c1, c2 = (uuid.uuid4() for _ in range(4))
    body = {
        "collection_id": str(collection),
        "version": version,
        "title": "Guide",
        "source_uri": "upload://guide.md",
        "acl_groups": ["staff"],
        "embedding_model": "m-1",
        "nodes": [
            {"id": str(root), "path": "d", "kind": "document", "title": "Guide"},
            {
                "id": str(c1),
                "parent_id": str(root),
                "path": "d.c0001",
                "kind": "chunk",
                "text": "Intro",
                "embedding": vec(0.1),
            },
            {
                "id": str(sec),
                "parent_id": str(root),
                "path": "d.s0002",
                "kind": "section",
                "title": "Setup",
                "heading_path": ["Setup"],
            },
            {
                "id": str(c2),
                "parent_id": str(sec),
                "path": "d.s0002.c0001",
                "kind": "chunk",
                "text": "Install it",
                "heading_path": ["Setup"],
                "page_start": 2,
                "page_end": 3,
                "token_count": 3,
                "embedding": vec(0.2),
            },
        ],
    }
    body.update(over)
    return body


def test_put_replace_outline_and_stats(setup: Setup) -> None:
    client, h = setup.client, setup.a
    collection, document = uuid.uuid4(), uuid.uuid4()
    r = client.put(f"/v1/index/documents/{document}", json=doc(collection), headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "document_id": str(document),
        "version": 1,
        "nodes": 4,
        "chunks": 2,
        "replaced": 0,
    }
    outline = client.get(f"/v1/index/documents/{document}/outline", headers=setup.staff).json()
    assert [n["path"] for n in outline["nodes"]] == ["d", "d.c0001", "d.s0002", "d.s0002.c0001"]
    r2 = client.put(f"/v1/index/documents/{document}", json=doc(collection, 2), headers=h)
    assert r2.json()["replaced"] == 4
    assert (
        client.put(
            f"/v1/index/documents/{document}", json=doc(collection, 1), headers=h
        ).status_code
        == 409
    )
    stats = client.get(f"/v1/index/collections/{collection}/stats", headers=setup.staff).json()
    assert (stats["documents"], stats["sections"], stats["chunks"]) == (1, 1, 2)
    # Outside the access group, the document's titles, headings and counts stay hidden (QA2-04).
    assert (
        client.get(f"/v1/index/documents/{document}/outline", headers=setup.member).status_code
        == 404
    )
    hidden = client.get(f"/v1/index/collections/{collection}/stats", headers=setup.member).json()
    assert (hidden["documents"], hidden["chunks"]) == (0, 0)
    # Tenant B sees and deletes nothing of tenant A's.
    assert client.get(f"/v1/index/documents/{document}/outline", headers=setup.b).status_code == 404
    assert client.delete(f"/v1/index/collections/{collection}", headers=setup.b).json() == {
        "deleted": 0
    }
    assert client.delete(f"/v1/index/collections/{collection}", headers=h).json() == {"deleted": 4}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["nodes"].pop(0),  # no root
        lambda b: b["nodes"][1].update(embedding=None),  # chunk without vector
        lambda b: b["nodes"][1].update(embedding=[0.1] * 3),  # wrong dimensions
        lambda b: b["nodes"][3].update(path="d.c0009"),  # path not under its parent
        lambda b: b["nodes"][3].update(parent_id=str(uuid.uuid4())),  # parent outside document
        lambda b: b["nodes"][2].update(path="d.s0002; DROP"),  # not an ltree path
    ],
)
def test_malformed_trees_are_rejected(setup: Setup, mutate: Any) -> None:
    client = setup.client
    body = doc(uuid.uuid4())
    mutate(body)
    assert (
        client.put(f"/v1/index/documents/{uuid.uuid4()}", json=body, headers=setup.a).status_code
        == 422
    )


def test_only_the_service_identity_writes(setup: Setup) -> None:
    client, t, mh = setup.client, setup.tenants, setup.member
    forged = TenantContext(t.a.context.tenant_id, "u", "user", frozenset({"service:ingestion"}))
    # A user token claiming the service role is refused before authorization even runs.
    assert (
        client.get("/v1/context", headers={CONTEXT_HEADER: t.issuer.issue(forged)}).status_code
        == 401
    )
    document = uuid.uuid4()
    assert (
        client.put(
            f"/v1/index/documents/{document}", json=doc(uuid.uuid4()), headers=mh
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/v1/index/documents/{document}", json=doc(uuid.uuid4()), headers=setup.a
        ).status_code
        == 200
    )
    assert (
        client.get(f"/v1/index/documents/{document}/outline", headers=setup.staff).status_code
        == 200
    )


def test_tenant_deletion(setup: Setup, retrieval_db: PgUrls) -> None:
    client, t = setup.client, setup.tenants
    client.put(f"/v1/index/documents/{uuid.uuid4()}", json=doc(uuid.uuid4()), headers=setup.a)

    async def run() -> Any:
        engine = create_engine(retrieval_db.app)
        try:
            return await IndexLifecycle("retrieval", TenantSessionFactory(engine)).delete_tenant(
                t.a.context.tenant_id
            )
        finally:
            await engine.dispose()

    report = asyncio.run(run())
    assert report.deleted == {"index_nodes": 4}
    assert report.residue_check_passed
