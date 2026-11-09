"""Extra Phase 2 ingestion QA cases. Synthetic content and local services only."""

import asyncio
import socket
import uuid

import httpx

from nexiqon_core.blobs import MemoryBlobStore
from nexiqon_core.fetch import FetchPolicy, SafeFetcher
from nexiqon_ingestion.plugins.connectors import S3Connector
from nexiqon_ingestion.plugins.context import Context

pytest_plugins = ["services.ingestion.tests.conftest"]


async def test_transient_crawl_failure_must_not_delete_indexed_documents(stack, monkeypatch):
    s = stack
    s.web.pages = {
        "/": ("text/html", '<h1>Home</h1><p>Welcome.</p><a href="/a">Guide</a>'),
        "/a": ("text/html", "<h1>Guide</h1><p>Keep this document.</p>"),
    }
    c = await s.collection()
    src = await s.ok(
        "POST",
        f"/v1/collections/{c['id']}/sources",
        201,
        json={
            "name": "qa-web",
            "connector": "web",
            "config": {"start_urls": ["https://docs.example.com/"]},
        },
    )
    first = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
    assert first["processed"] == 2
    original = type(s.web).__call__

    def unavailable(self, request):
        if request.url.path == "/a":
            return httpx.Response(503, text="temporarily unavailable")
        return original(self, request)

    monkeypatch.setattr(type(s.web), "__call__", unavailable)
    second = await s.wait(await s.ok("POST", f"/v1/sources/{src['id']}/sync", 202))
    docs = await s.ok("GET", f"/v1/collections/{c['id']}/documents")
    print(
        "second sync:",
        second["status"],
        "warnings:",
        second["warnings"],
        "deleted:",
        second["deleted"],
        "remaining:",
        [d["uri"] for d in docs],
    )
    assert second["deleted"] == 0, (
        "A temporary HTTP 503 must not delete a previously indexed document"
    )
    assert len(docs) == 2


async def test_s3_dns_rebinding_must_not_reach_loopback(tmp_path, monkeypatch):
    hits = []

    async def local_server(reader, writer):
        headers = await reader.readuntil(b"\r\n\r\n")
        hits.append(headers.splitlines()[0].decode())
        body = b"<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>"
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(local_server, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    original = socket.getaddrinfo

    def rebinding(host, port, *args, **kwargs):
        normalized = host.decode() if isinstance(host, bytes) else host
        return original(
            "127.0.0.1" if normalized == "s3.qa.example" else host, port, *args, **kwargs
        )

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)

    async def public_check(host, port):
        return ["93.184.216.34"]

    fetch = SafeFetcher(FetchPolicy(allowed_ports=[port]), resolver=public_check)
    tenant = uuid.uuid4()
    ctx = Context(
        tenant_id=tenant,
        http=fetch,
        blobs=MemoryBlobStore(),
        scratch=tmp_path,
        credentials={f"{tenant}/qa": {"access_key": "qa", "secret_key": "qa"}},
        max_items=10,
        max_bytes=10000,
    )
    try:
        items = [
            i
            async for i in S3Connector().discover(
                ctx,
                {
                    "endpoint": f"http://s3.qa.example:{port}",
                    "bucket": "docs",
                    "credentials_ref": "qa",
                },
            )
        ]
        print(
            "checked address: 93.184.216.34; actual loopback requests:", hits, "items:", len(items)
        )
        assert not hits, "S3 connected to loopback after its safety check approved a public address"
    finally:
        await fetch.aclose()
        server.close()
        await server.wait_closed()
