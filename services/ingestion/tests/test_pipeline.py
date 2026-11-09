"""End-to-end ingestion (IN-02, IN-05, IN-07, IN-08) through Temporal workflows."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_ingestion.models import Outbox
from nexiqon_ingestion.testing import EICAR

from .conftest import Stack
from .docs import MARKDOWN, docx, pdf

pytestmark = pytest.mark.integration


async def outline(s: Stack, document_id: str, headers: dict[str, str] | None = None) -> Any:
    r = await s.retrieval.get(f"/v1/index/documents/{document_id}/outline", headers=headers or s.h)
    return r


async def events(s: Stack, url: str) -> list[str]:
    engine = create_engine(url)
    try:
        async with TenantSessionFactory(engine).system_session() as session:
            rows = await session.scalars(
                select(Outbox.type)
                .where(Outbox.tenant_id == s.tenants.a.context.tenant_id)
                .order_by(Outbox.created_at)
            )
            return list(rows)
    finally:
        await engine.dispose()


async def test_upload_index_replace_and_delete(stack: Stack) -> None:
    s = stack
    c = await s.collection()
    up = await s.upload(c["id"], "guide.md", MARKDOWN.encode(), "text/markdown")
    run = await s.wait(
        {
            "id": up["run_id"],
            "workflow_id": (await s.ok("GET", f"/v1/runs/{up['run_id']}"))["workflow_id"],
        }
    )
    assert run["status"] == "completed"
    assert run["processed"] == 1
    doc = await s.ok("GET", f"/v1/documents/{up['document']['id']}")
    assert doc["status"] == "ready"
    assert doc["title"] == "Platform Guide"
    assert doc["section_count"] == 3
    assert doc["chunk_count"] == 4
    assert doc["scanner"] == "fake-av"
    tree = (await outline(s, doc["id"])).json()
    assert [n["path"] for n in tree["nodes"]][:3] == ["d", "d.c0001", "d.s0002"]
    assert tree["version"] == 1
    assert (await s.ok("GET", f"/v1/collections/{c['id']}"))[
        "embedding_model"
    ] == "text-embedding-3-small"
    # Embedding calls carried the collection's profile and classification, with section context.
    call = s.gateway.calls[0]
    assert (call["profile"], call["classification"]) == ("cloud-frontier", "internal")
    assert any(t.startswith("Platform Guide > Getting started\n\n") for t in call["inputs"])

    same = await s.upload(c["id"], "guide.md", MARKDOWN.encode(), "text/markdown")
    assert same["unchanged"] is True
    assert same["run_id"] is None

    changed = await s.upload(
        c["id"],
        "guide.md",
        MARKDOWN.replace("Run it daily.", "Run it hourly.").encode(),
        "text/markdown",
    )
    run2 = await s.ok("GET", f"/v1/runs/{changed['run_id']}")
    await s.wait(run2)
    tree2 = (await outline(s, doc["id"])).json()
    assert tree2["version"] == 2
    assert not {n["id"] for n in tree["nodes"]} & {
        n["id"] for n in tree2["nodes"]
    }  # old nodes gone
    assert len(s.blobs.objects) == 1  # the previous file version was removed

    await s.ok("DELETE", f"/v1/documents/{doc['id']}", 204)
    assert (await outline(s, doc["id"])).status_code == 404
    assert s.blobs.objects == {}
    assert (await s.api.get(f"/v1/documents/{doc['id']}", headers=s.h)).status_code == 404
    kinds = await events(s, s.app.state.settings.database.url.get_secret_value())
    assert kinds.count("nexiqon.ingestion.document.indexed") == 2
    assert "nexiqon.ingestion.document.deleted" in kinds
    assert kinds.count("nexiqon.ingestion.run.completed") == 2


async def test_formats_malware_and_failures(stack: Stack) -> None:
    s = stack
    c = await s.collection()
    uploads = [
        (
            "manual.pdf",
            pdf(["Alpha text.", "Beta text."], outline=[("Alpha", 0), ("Beta", 1)]),
            "application/pdf",
        ),
        (
            "policy.docx",
            docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("virus.txt", EICAR, "text/plain"),  # ClamAV matches EICAR only at the file start
        ("archive.zip", b"PK\x03\x04", "application/zip"),
        ("blank.txt", b"   \n\n  ", "text/plain"),
    ]
    results: dict[str, dict[str, Any]] = {}
    for name, body, media in uploads:
        up = await s.upload(c["id"], name, body, media)
        await s.wait(await s.ok("GET", f"/v1/runs/{up['run_id']}"))
        results[name] = await s.ok("GET", f"/v1/documents/{up['document']['id']}")
    assert results["manual.pdf"]["status"] == "ready"
    pdf_tree = (await outline(s, results["manual.pdf"]["id"])).json()["nodes"]
    assert [(n["title"], n["page_start"]) for n in pdf_tree if n["kind"] == "section"] == [
        ("Alpha", 1),
        ("Beta", 2),
    ]
    assert results["policy.docx"]["status"] == "ready"
    virus = results["virus.txt"]
    assert (virus["status"], virus["error_code"]) == ("quarantined", "malware_detected")
    assert (await outline(s, virus["id"])).status_code == 404
    assert results["archive.zip"]["error_code"] == "unsupported_type"
    assert results["blank.txt"]["error_code"] == "empty_document"
    runs = await s.ok("GET", f"/v1/collections/{c['id']}/runs")
    assert sum(r["quarantined"] for r in runs) == 1
    assert sum(r["failed"] for r in runs) == 2
    docs = await s.ok("GET", f"/v1/collections/{c['id']}/documents")
    assert len(docs) == 5


async def test_restricted_collection_cannot_use_cloud_embeddings(stack: Stack) -> None:
    s = stack
    c = await s.collection(classification="restricted")
    up = await s.upload(c["id"], "secret.md", b"# Secret\n\nText.", "text/markdown")
    await s.wait(await s.ok("GET", f"/v1/runs/{up['run_id']}"))
    doc = await s.ok("GET", f"/v1/documents/{up['document']['id']}")
    assert (doc["status"], doc["error_code"]) == ("failed", "embedding_failed")
    assert "cloud" in doc["error_detail"]


async def test_transient_failures_are_retried(stack: Stack) -> None:
    s = stack
    c = await s.collection()
    s.gateway.fail_next = [503, 503]
    up = await s.upload(c["id"], "a.md", b"# A\n\nText.", "text/markdown")
    run = await s.wait(await s.ok("GET", f"/v1/runs/{up['run_id']}"))
    assert run["processed"] == 1
    assert len(s.gateway.calls) == 3


async def test_web_sync_detects_changes_and_deletions(stack: Stack) -> None:
    s = stack
    s.web.pages = {
        "/": (
            "text/html",
            '<main><h1>Home</h1><p>Start.</p><a href="/a">A</a> <a href="/b">B</a></main>',
        ),
        "/a": ("text/html", "<main><h1>A</h1><p>Alpha page.</p></main>"),
        "/b": ("text/html", "<main><h1>B</h1><p>Beta page.</p></main>"),
    }
    c = await s.collection()
    src = await s.ok(
        "POST",
        f"/v1/collections/{c['id']}/sources",
        201,
        json={
            "name": "docs-site",
            "connector": "web",
            "config": {"start_urls": ["https://docs.example.com/"]},
        },
    )
    first = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
    assert (first["status"], first["discovered"], first["processed"]) == ("completed", 3, 3)
    calls = len(s.gateway.calls)

    s.web.pages["/b"] = ("text/html", "<main><h1>B</h1><p>Beta page, revised.</p></main>")
    second = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
    assert (second["processed"], second["unchanged"]) == (1, 2)
    assert len(s.gateway.calls) == calls + 1  # only the changed page was re-embedded

    s.web.pages["/"] = ("text/html", '<main><h1>Home</h1><p>Start.</p><a href="/a">A</a></main>')
    del s.web.pages["/b"]
    third = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
    assert third["deleted"] == 1
    docs = await s.ok("GET", f"/v1/collections/{c['id']}/documents")
    assert sorted(d["uri"] for d in docs) == [
        "https://docs.example.com/",
        "https://docs.example.com/a",
    ]
    stats = (await s.retrieval.get(f"/v1/index/collections/{c['id']}/stats", headers=s.h)).json()
    assert stats["documents"] == 2


async def test_sources_are_validated_and_ssrf_is_refused(stack: Stack) -> None:
    s = stack
    c = await s.collection()
    bad = await s.api.post(
        f"/v1/collections/{c['id']}/sources",
        headers=s.h,
        json={"name": "bad", "connector": "web", "config": {"start_urls": []}},
    )
    assert bad.status_code == 400
    assert bad.json()["errors"]
    unknown = await s.api.post(
        f"/v1/collections/{c['id']}/sources",
        headers=s.h,
        json={"name": "ftp-src", "connector": "ftp", "config": {}},
    )
    assert unknown.status_code == 400
    src = await s.ok(
        "POST",
        f"/v1/collections/{c['id']}/sources",
        201,
        json={
            "name": "intranet",
            "connector": "web",
            "config": {"start_urls": ["http://intranet.example.com/"]},
        },
    )
    run = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
    assert run["status"] == "failed"
    assert "non-public" in run["error"]
    sources = await s.ok("GET", f"/v1/collections/{c['id']}/sources")
    assert next(x for x in sources if x["name"] == "intranet")["status"] == "idle"
    assert "intranet" not in str(s.web.requests)


async def test_model_change_reindexes_into_the_new_vector_space(stack: Stack) -> None:
    s = stack
    c = await s.collection()
    up = await s.upload(
        c["id"], "a.md", b"# A\n\n## One\n\nFirst.\n\n## Two\n\nSecond.", "text/markdown"
    )
    await s.wait(await s.ok("GET", f"/v1/runs/{up['run_id']}"))
    await s.ok("PATCH", f"/v1/collections/{c['id']}", json={"model_profile": "on-prem-standard"})
    runs = await s.ok("GET", f"/v1/collections/{c['id']}/runs")
    reindex = next(r for r in runs if r["kind"] == "reindex")
    done = await s.wait(reindex)
    assert done["processed"] == 1
    assert (await s.ok("GET", f"/v1/collections/{c['id']}"))[
        "embedding_model"
    ] == "qwen3-embedding-0.6b"
    assert s.gateway.calls[-1]["profile"] == "on-prem-standard"


async def test_tenants_are_isolated_and_members_read_only(stack: Stack) -> None:
    s = stack
    c = await s.collection()
    up = await s.upload(c["id"], "a.md", b"# A\n\nText.", "text/markdown")
    await s.wait(await s.ok("GET", f"/v1/runs/{up['run_id']}"))
    other = s.tenants.b.headers
    assert (await s.api.get(f"/v1/collections/{c['id']}", headers=other)).status_code == 404
    assert (await s.api.get("/v1/collections", headers=other)).json() == []
    assert (
        await s.api.get(f"/v1/documents/{up['document']['id']}", headers=other)
    ).status_code == 404
    assert (await outline(s, up["document"]["id"], other)).status_code == 404
    # The index API refuses user tokens for writes (service identity only in OPA; here: no grant).
    from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext

    member = TenantContext(s.tenants.a.context.tenant_id, "m-1", "user", frozenset({"member"}))
    mh = {CONTEXT_HEADER: s.tenants.issuer.issue(member)}
    assert (
        await s.api.post("/v1/collections", headers=mh, json={"name": "nope"})
    ).status_code == 403
    assert (await s.api.get("/v1/collections", headers=mh)).status_code == 200
    put = await s.retrieval.delete(f"/v1/index/documents/{up['document']['id']}", headers=mh)
    assert put.status_code == 403


async def test_plugins_gallery_and_collection_delete(stack: Stack) -> None:
    s = stack
    gallery = await s.ok("GET", "/v1/plugins", params={"kind": "connector"})
    assert {p["name"] for p in gallery} >= {"upload", "web", "s3", "git"}
    web = next(p for p in gallery if p["name"] == "web")
    assert "start_urls" in web["config_schema"]["properties"]
    c = await s.collection()
    up = await s.upload(c["id"], "a.md", b"# A\n\nText.", "text/markdown")
    await s.wait(await s.ok("GET", f"/v1/runs/{up['run_id']}"))
    await s.ok("DELETE", f"/v1/collections/{c['id']}", 204)
    assert (await outline(s, up["document"]["id"])).status_code == 404
    assert s.blobs.objects == {}
    assert (await s.api.get(f"/v1/collections/{c['id']}", headers=s.h)).status_code == 404


async def test_killed_worker_resumes(stack: Stack) -> None:
    """IN-02: a worker dies mid-embedding; a new worker finishes the same workflow."""
    import asyncio

    from temporalio.worker import Worker

    from nexiqon_ingestion.workflows import WORKFLOWS

    s = stack
    c = await s.collection()
    s.gateway.hold = asyncio.Event()
    up = await s.upload(c["id"], "a.md", b"# A\n\nText.", "text/markdown")
    run = await s.ok("GET", f"/v1/runs/{up['run_id']}")
    for _ in range(200):
        if s.gateway.waiting:
            break
        await asyncio.sleep(0.05)
    assert s.gateway.waiting, "the embedding call never started"
    await s.app.state.worker.shutdown()  # the in-flight activity is abandoned
    s.gateway.hold = None
    pipeline = s.app.state.pipeline
    async with Worker(
        s.env.client,
        task_queue="ingestion-test",
        workflows=WORKFLOWS,
        activities=pipeline.activities(),
        max_cached_workflows=0,
    ):
        await s.env.client.get_workflow_handle(run["workflow_id"]).result()
        done = await s.ok("GET", f"/v1/runs/{run['id']}")
    assert done["status"] == "completed"
    assert done["processed"] == 1
    doc = await s.ok("GET", f"/v1/documents/{up['document']['id']}")
    assert doc["status"] == "ready"


# ---------------------------------------------------------------- QA 2026-11-09 regressions


async def test_qa2_03_transient_crawl_failures_never_delete(stack: Stack) -> None:
    s = stack
    s.web.pages = {
        "/": ("text/html", '<main><h1>Home</h1><p>Start.</p><a href="/a">A</a></main>'),
        "/a": ("text/html", "<main><h1>A</h1><p>Keep this page.</p></main>"),
    }
    c = await s.collection()
    src = await s.ok(
        "POST",
        f"/v1/collections/{c['id']}/sources",
        201,
        json={
            "name": "site",
            "connector": "web",
            "config": {"start_urls": ["https://docs.example.com/"]},
        },
    )
    assert (await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202)))[
        "processed"
    ] == 2
    for status in (503, 429, 403):  # outage, rate limit, refusal: none proves removal
        s.web.fail["/a"] = status
        run = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
        assert (run["status"], run["incomplete"], run["deleted"]) == ("completed", True, 0), status
        assert run["warnings"][0]["message"] == f"HTTP {status}"
        assert len(await s.ok("GET", f"/v1/collections/{c['id']}/documents")) == 2
    s.web.fail = {
        "/robots.txt": 500
    }  # robots.txt unavailable: the site is skipped, nothing deleted
    run = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
    assert (run["incomplete"], run["deleted"]) == (True, 0)
    s.web.fail = {}
    del s.web.pages["/a"]  # still linked, but now 404: authoritative removal
    run = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
    assert (run["incomplete"], run["deleted"]) == (False, 1)


async def test_qa2_04_collections_with_access_groups_are_hidden_from_other_members(
    stack: Stack,
) -> None:
    from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext

    s = stack
    c = await s.collection(name="legal", acl_groups=["legal"])
    up = await s.upload(c["id"], "deal.md", b"# Secret acquisition\n\nTerms.", "text/markdown")
    await s.wait(await s.ok("GET", f"/v1/runs/{up['run_id']}"))
    tenant = s.tenants.a.context.tenant_id

    def as_(roles: set[str], groups: set[str]) -> dict[str, str]:
        ctx = TenantContext(tenant, "u-1", "user", frozenset(roles), frozenset(groups))
        return {CONTEXT_HEADER: s.tenants.issuer.issue(ctx)}

    outsider = as_({"member"}, {"engineering"})
    for path in (
        f"/v1/collections/{c['id']}",
        f"/v1/collections/{c['id']}/documents",
        f"/v1/collections/{c['id']}/sources",
        f"/v1/collections/{c['id']}/runs",
        f"/v1/documents/{up['document']['id']}",
        f"/v1/runs/{up['run_id']}",
    ):
        assert (await s.api.get(path, headers=outsider)).status_code == 404, path
    assert (await s.api.get("/v1/collections", headers=outsider)).json() == []
    insider = as_({"member"}, {"legal"})
    assert (
        await s.api.get(f"/v1/documents/{up['document']['id']}", headers=insider)
    ).status_code == 200
    editor = as_({"editor"}, set())
    assert [x["name"] for x in (await s.api.get("/v1/collections", headers=editor)).json()] == [
        "legal"
    ]
