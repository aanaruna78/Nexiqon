"""SSRF-safe fetcher (IN-04): every hop is resolved, checked and pinned."""

from __future__ import annotations

import httpx
import pytest

from nexiqon_core.fetch import FetchBlocked, FetchPolicy, FetchTooLarge, SafeFetcher

DNS = {
    "docs.example.com": ["93.184.216.34"],
    "internal.example.com": ["10.0.0.5"],
    "mixed.example.com": ["93.184.216.34", "127.0.0.1"],
    "metadata.example.com": ["169.254.169.254"],
    "v6.example.com": ["2606:4700::1111"],
    "mapped.example.com": ["::ffff:127.0.0.1"],
    "cgnat.example.com": ["100.64.0.1"],
    "rebind.example.com": ["93.184.216.35"],
}


async def resolver(host: str, port: int) -> list[str]:
    if host in DNS:
        return DNS[host]
    # Literal addresses resolve to themselves (as getaddrinfo does).
    return [host]


def fetcher(handler: httpx.MockTransport | None = None, **policy: object) -> SafeFetcher:
    seen: list[httpx.Request] = []

    def default(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="ok", headers={"content-type": "text/html; charset=utf-8"})

    f = SafeFetcher(
        FetchPolicy(**policy),  # type: ignore[arg-type]
        resolver=resolver,
        transport=handler or httpx.MockTransport(default),
    )
    f.seen = seen  # type: ignore[attr-defined]
    return f


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost.localdomain.invalid/",  # unresolvable names are not "allowed by default"
        "http://internal.example.com/",
        "http://mixed.example.com/",
        "http://metadata.example.com/latest/meta-data/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://mapped.example.com/",
        "http://cgnat.example.com/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "file:///etc/passwd",
        "gopher://docs.example.com/",
        "http://docs.example.com:22/",
        "http://user:pass@docs.example.com/",
    ],
)
async def test_blocks_non_public_targets(url: str) -> None:
    f = fetcher()
    with pytest.raises(FetchBlocked) if "invalid" not in url else pytest.raises(Exception):  # noqa: PT011
        await f.get(url)
    assert f.seen == []  # type: ignore[attr-defined]


async def test_connection_is_pinned_to_the_checked_address() -> None:
    f = fetcher()
    result = await f.get("https://docs.example.com/guide?x=1")
    req = f.seen[0]  # type: ignore[attr-defined]
    assert req.url.host == "93.184.216.34"
    assert req.headers["host"] == "docs.example.com"
    assert req.extensions["sni_hostname"] == "docs.example.com"
    assert result.content == b"ok"
    assert result.content_type == "text/html"
    v6 = fetcher()
    await v6.get("https://v6.example.com/")
    assert v6.seen[0].url.host == "2606:4700::1111"  # type: ignore[attr-defined]


async def test_redirects_are_rechecked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://internal.example.com/admin"})
        return httpx.Response(200, text="never")

    f = fetcher(httpx.MockTransport(handler))
    with pytest.raises(FetchBlocked):
        await f.get("http://docs.example.com/start")

    def ok_redirect(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(200, text="final")

    result = await fetcher(httpx.MockTransport(ok_redirect)).get("http://docs.example.com/start")
    assert result.content == b"final"
    assert result.url.endswith("/final")


async def test_size_cap_and_allowed_private_ranges() -> None:
    def big(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2048)

    with pytest.raises(FetchTooLarge):
        await fetcher(httpx.MockTransport(big), max_bytes=1024).get("http://docs.example.com/")
    intranet = fetcher(allowed_private_cidrs=["10.0.0.0/8"])
    assert (await intranet.get("http://internal.example.com/")).status == 200
    with pytest.raises(FetchBlocked):
        await intranet.get("http://127.0.0.1/")


async def test_conditional_requests_report_not_modified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text="body", headers={"etag": '"v1"'})

    f = fetcher(httpx.MockTransport(handler))
    first = await f.get("http://docs.example.com/")
    again = await f.get(
        "http://docs.example.com/", headers={"if-none-match": first.headers["etag"]}
    )
    assert again.not_modified
