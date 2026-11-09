"""Test doubles for ingestion: model gateway, scanner, a small website, and a host router."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from typing import Any, ClassVar

import httpx

from nexiqon_core.scanning import ScanResult
from nexiqon_sdk import Content, Item, Manifest, PluginKind

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class FakeScanner:
    name = "fake-av"

    async def scan(self, data: bytes) -> ScanResult:
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data:
            return ScanResult(clean=False, signature="Eicar-Test-Signature", scanner=self.name)
        return ScanResult(clean=True, scanner=self.name)


def vector(text: str) -> list[float]:
    seed = hashlib.sha256(text.encode()).digest()
    return [((seed[i % 32] + i) % 97) / 97 for i in range(1024)]


class FakeModelGateway:
    """Answers /v1/embeddings like the model gateway (model name follows the profile)."""

    MODELS: ClassVar[dict[str, str]] = {
        "cloud-frontier": "text-embedding-3-small",
        "on-prem-standard": "qwen3-embedding-0.6b",
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_next: list[int] = []  # HTTP statuses to return before succeeding
        self.hold: asyncio.Event | None = None  # block calls until set (simulates a slow model)
        self.waiting = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if self.hold is not None:
            self.waiting += 1
            await self.hold.wait()
        self.calls.append(body)
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"detail": "unavailable"})
        if body.get("classification") == "restricted" and body["profile"] == "cloud-frontier":
            return httpx.Response(
                403, json={"detail": "restricted data may not be sent to cloud model profile"}
            )
        model = self.MODELS.get(body["profile"], "fake-embed")
        return httpx.Response(
            200,
            json={
                "vectors": [vector(t) for t in body["inputs"]],
                "dimensions": 1024,
                "route": {"profile": body["profile"], "model": model},
                "usage": {"input_tokens": 1, "output_tokens": 0},
                "cost_usd": "0",
            },
        )


class HostRouter(httpx.AsyncBaseTransport):
    """Routes requests to per-host transports (ASGI apps or mocks)."""

    def __init__(self, routes: dict[str, httpx.AsyncBaseTransport]) -> None:
        self.routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        transport = self.routes.get(request.url.host)
        if transport is None:
            return httpx.Response(502, json={"detail": f"no route to {request.url.host}"})
        return await transport.handle_async_request(request)


class FakeWeb:
    """A tiny website served by address (the fetcher pins connections to resolved IPs)."""

    HOST = "docs.example.com"
    ADDRESS = "93.184.216.34"

    def __init__(self) -> None:
        self.pages: dict[str, tuple[str, str]] = {}  # path -> (content type, body)
        self.robots = "User-agent: *\nDisallow: /private/\n"
        self.requests: list[str] = []
        self.fail: dict[str, int] = {}  # path -> HTTP status to return (transient outages)

    async def resolve(self, host: str, port: int) -> list[str]:
        return {self.HOST: [self.ADDRESS], "intranet.example.com": ["10.1.2.3"]}.get(host, [host])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if path in self.fail:
            return httpx.Response(self.fail[path], text="temporarily unavailable")
        if path == "/robots.txt":
            return httpx.Response(200, text=self.robots)
        if path not in self.pages:
            return httpx.Response(404, text="missing")
        media, body = self.pages[path]
        etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:16] + '"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        return httpx.Response(200, text=body, headers={"content-type": media, "etag": etag})


class SampleConnector:
    """A plugin defined outside the core, used to prove entry-point discovery."""

    manifest = Manifest(
        name="sample",
        kind=PluginKind.CONNECTOR,
        title="Sample",
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["count"],
            "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 5}},
        },
        capabilities=["discover"],
    )

    async def discover(self, ctx: Any, config: Any) -> Any:
        for i in range(int(config["count"])):
            yield Item(uri=f"sample://{i}", title=f"Item {i}")

    async def fetch(
        self, ctx: Any, config: Any, item: Item, previous_version: str | None
    ) -> Content:
        return Content(
            uri=item.uri,
            data=f"# {item.title}\n\nBody of {item.title}.".encode(),
            media_type="text/markdown",
        )


def sample_plugins() -> list[Any]:
    return [SampleConnector()]


Handler = Callable[[httpx.Request], httpx.Response]
