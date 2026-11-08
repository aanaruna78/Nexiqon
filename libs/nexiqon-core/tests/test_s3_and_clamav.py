"""S3 SigV4 signing (AWS published test vector), S3 list parsing and the clamd protocol."""

from __future__ import annotations

import asyncio
import struct
from datetime import UTC, datetime

import httpx
import pytest

from nexiqon_core.adapters.clamav import ClamdScanner
from nexiqon_core.adapters.s3 import EMPTY_SHA256, S3Client, sign_v4
from nexiqon_core.blobs import MemoryBlobStore, tenant_key
from nexiqon_core.scanning import ScanUnavailable

EICAR_NAME = "Win.Test.EICAR_HDB-1"


def test_sigv4_matches_aws_example() -> None:
    # "GET Object" example from the AWS S3 Signature Version 4 documentation.
    url = httpx.URL("https://examplebucket.s3.amazonaws.com/test.txt")
    headers = {
        "host": "examplebucket.s3.amazonaws.com",
        "range": "bytes=0-9",
        "x-amz-content-sha256": EMPTY_SHA256,
        "x-amz-date": "20130524T000000Z",
    }
    auth = sign_v4(
        "GET",
        url,
        headers,
        EMPTY_SHA256,
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        now=datetime(2013, 5, 24, tzinfo=UTC),
    )
    assert auth.endswith(
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in auth


async def test_list_objects_follows_continuation() -> None:
    pages = {
        None: b"""<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
          <IsTruncated>true</IsTruncated><NextContinuationToken>t2</NextContinuationToken>
          <Contents><Key>docs/a.md</Key><Size>10</Size><ETag>"e1"</ETag><LastModified>2026-11-01T00:00:00Z</LastModified></Contents>
        </ListBucketResult>""",
        "t2": b"""<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>
          <Contents><Key>docs/b.md</Key><Size>20</Size><ETag>"e2"</ETag><LastModified>x</LastModified></Contents>
        </ListBucketResult>""",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=ak/")
        return httpx.Response(200, content=pages[request.url.params.get("continuation-token")])

    client = S3Client(
        "https://s3.example.com", "us-east-1", "ak", "sk", transport=httpx.MockTransport(handler)
    )
    objects = await client.list_objects("bucket", "docs/")
    assert [(o.key, o.size, o.etag) for o in objects] == [
        ("docs/a.md", 10, "e1"),
        ("docs/b.md", 20, "e2"),
    ]


async def test_tenant_keys_and_memory_store() -> None:
    import uuid

    t = uuid.uuid4()
    key = tenant_key(t, "documents", "abc", "raw")
    assert key.startswith(f"t/{t}/")
    with pytest.raises(ValueError, match="unsafe"):
        tenant_key(t, "..", "other")
    store = MemoryBlobStore()
    await store.put(key, b"data", "text/plain")
    assert await store.get(key) == b"data"


async def _fake_clamd(reply: bytes) -> tuple[asyncio.Server, int, list[bytes]]:
    received: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        data = b""
        while True:
            (size,) = struct.unpack("!L", await reader.readexactly(4))
            if size == 0:
                break
            data += await reader.readexactly(size)
        received.append(data)
        writer.write(reply)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], received


async def test_clamd_instream_verdicts() -> None:
    server, port, received = await _fake_clamd(f"stream: {EICAR_NAME} FOUND\0".encode())
    async with server:
        result = await ClamdScanner("127.0.0.1", port).scan(b"X" * 100_000)
    assert not result.clean
    assert result.signature == EICAR_NAME
    assert received == [b"X" * 100_000]
    server, port, _ = await _fake_clamd(b"stream: OK\0")
    async with server:
        assert (await ClamdScanner("127.0.0.1", port).scan(b"hello")).clean
    with pytest.raises(ScanUnavailable):
        await ClamdScanner("127.0.0.1", 1, timeout=2).scan(b"x")
