"""SSRF-safe HTTP fetching for anything that follows customer-supplied URLs (IN-04).

Used by ingestion connectors and the tool gateway. For every hop (including each redirect):

* only allowed schemes and ports;
* the host is resolved once and **every** resolved address must be public (``is_global``), unless it
  falls in an operator-allowed CIDR (on-prem intranets). Loopback, private, link-local (cloud
  metadata), CGNAT, multicast and reserved ranges are refused; IPv4-mapped IPv6 is unwrapped;
* the connection is **pinned** to the checked address (Host header and TLS SNI keep the name), so
  DNS rebinding between check and connect cannot redirect the request;
* redirects are followed manually and re-checked; bodies are streamed with a size cap.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field

from nexiqon_core.errors import NexiqonError

Resolver = Callable[[str, int], Awaitable[list[str]]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
REDIRECTS = {301, 302, 303, 307, 308}


class FetchPolicy(BaseModel):
    allowed_schemes: list[str] = Field(default_factory=lambda: ["https", "http"])
    allowed_ports: list[int] = Field(default_factory=lambda: [80, 443, 8080, 8443])
    # CIDRs that may be reached although not public (e.g. a customer intranet in on-prem mode).
    allowed_private_cidrs: list[str] = Field(default_factory=list)
    max_bytes: int = 25 * 1024 * 1024
    timeout_seconds: float = 20.0
    max_redirects: int = 5
    user_agent: str = "NexiqonBot/0.1"


class FetchBlocked(NexiqonError):
    status, code, title = 400, "fetch_blocked", "Address not allowed"


class FetchFailed(NexiqonError):
    status, code, title = 502, "fetch_failed", "Fetch failed"


class FetchTooLarge(NexiqonError):
    status, code, title = 413, "fetch_too_large", "Content too large"


@dataclass
class FetchResult:
    url: str
    status: int
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return sorted({str(info[4][0]) for info in infos})


class SafeFetcher:
    def __init__(
        self,
        policy: FetchPolicy | None = None,
        *,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.policy = policy or FetchPolicy()
        self._resolve = resolver or system_resolver
        self._allowed = [
            ipaddress.ip_network(c, strict=False) for c in self.policy.allowed_private_cidrs
        ]
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=self.policy.timeout_seconds,
            follow_redirects=False,
            trust_env=False,  # never route through ambient proxies
        )

    def is_allowed_ip(self, raw: str) -> bool:
        ip: IPAddress = ipaddress.ip_address(raw.split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if any(ip in net for net in self._allowed):
            return True
        return ip.is_global and not ip.is_multicast

    async def check(self, url: str) -> tuple[httpx.URL, str]:
        """Validate ``url`` and return it with the address to connect to. Raises FetchBlocked."""
        try:
            parsed = httpx.URL(url)
        except (httpx.InvalidURL, ValueError) as exc:
            raise FetchBlocked("Invalid URL") from exc
        if parsed.scheme not in self.policy.allowed_schemes:
            raise FetchBlocked(f"Scheme {parsed.scheme!r} is not allowed")
        if not parsed.host:
            raise FetchBlocked("URL has no host")
        if parsed.userinfo:
            raise FetchBlocked("Credentials in URLs are not allowed")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in self.policy.allowed_ports:
            raise FetchBlocked(f"Port {port} is not allowed")
        try:
            addresses = await self._resolve(parsed.host, port)
        except OSError as exc:
            raise FetchFailed(f"Cannot resolve {parsed.host}") from exc
        if not addresses:
            raise FetchFailed(f"Cannot resolve {parsed.host}")
        # Every address must pass, or an attacker could mix one public and one private record.
        for address in addresses:
            if not self.is_allowed_ip(address):
                raise FetchBlocked(f"{parsed.host} resolves to a non-public address")
        return parsed, addresses[0]

    async def get(self, url: str, headers: dict[str, str] | None = None) -> FetchResult:
        current = url
        for _ in range(self.policy.max_redirects + 1):
            parsed, address = await self.check(current)
            response = await self._send(parsed, address, headers or {})
            if response.status in REDIRECTS and "location" in response.headers:
                current = urljoin(current, response.headers["location"])
                continue
            return response
        raise FetchFailed("Too many redirects")

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        timeout_seconds: float | None = None,
    ) -> FetchResult:
        """One checked, pinned request without following redirects (tool calls: a redirect must not
        move a write somewhere else). A 3xx is returned to the caller as-is."""
        parsed, address = await self.check(url)
        return await self._send(
            parsed,
            address,
            headers or {},
            method=method,
            content=content,
            timeout_seconds=timeout_seconds,
        )

    async def _send(
        self,
        parsed: httpx.URL,
        address: str,
        headers: dict[str, str],
        *,
        method: str = "GET",
        content: bytes | None = None,
        timeout_seconds: float | None = None,
    ) -> FetchResult:
        pinned = parsed.copy_with(host=address)  # connect to the checked address only
        host_header = parsed.host if parsed.port is None else f"{parsed.host}:{parsed.port}"
        request_headers = {
            "user-agent": self.policy.user_agent,
            "accept-encoding": "identity",  # the size cap applies to what we store
            **headers,
            "host": host_header,
        }
        extensions: dict[str, Any] = (
            {"sni_hostname": parsed.host} if parsed.scheme == "https" else {}
        )
        if timeout_seconds is not None:
            extensions["timeout"] = httpx.Timeout(timeout_seconds).as_dict()
        request = self._client.build_request(
            method, pinned, headers=request_headers, content=content, extensions=extensions
        )
        try:
            response = await self._client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise FetchFailed(f"Timed out fetching {parsed.host}") from exc
        except httpx.HTTPError as exc:
            raise FetchFailed(f"Could not fetch from {parsed.host}") from exc
        try:
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.policy.max_bytes:
                raise FetchTooLarge(f"Content exceeds {self.policy.max_bytes} bytes")
            chunks: list[bytes] = []
            size = 0
            async for (
                chunk
            ) in response.aiter_bytes():  # decoded: the cap also stops decompression bombs
                size += len(chunk)
                if size > self.policy.max_bytes:
                    raise FetchTooLarge(f"Content exceeds {self.policy.max_bytes} bytes")
                chunks.append(chunk)
        finally:
            await response.aclose()
        return FetchResult(
            url=str(parsed),
            status=response.status_code,
            content=b"".join(chunks),
            headers={k.lower(): v for k, v in response.headers.items()},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
