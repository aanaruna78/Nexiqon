"""Connectors (IN-03) and plugin discovery (IN-01), without network or Temporal."""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import httpx
import pytest

from nexiqon_core.blobs import MemoryBlobStore
from nexiqon_core.fetch import FetchBlocked, FetchPolicy, SafeFetcher
from nexiqon_ingestion.plugins.connectors import GitConnector, S3Connector, WebCrawler
from nexiqon_ingestion.plugins.context import Context, MissingCredentials
from nexiqon_ingestion.testing import FakeWeb
from nexiqon_sdk import Item, PluginError, PluginKind, Registry

TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


def context(tmp_path: Path, web: FakeWeb | None = None, handler: Any = None, **kw: Any) -> Context:
    web = web or FakeWeb()
    transport = httpx.MockTransport(handler or web)
    return Context(
        tenant_id=TENANT,
        http=SafeFetcher(FetchPolicy(), resolver=web.resolve, transport=transport),
        blobs=MemoryBlobStore(),
        scratch=tmp_path,
        credentials=kw.pop("credentials", {}),
        max_items=kw.pop("max_items", 100),
        max_bytes=1_000_000,
        transport=transport,
    )


def site() -> FakeWeb:
    web = FakeWeb()
    web.pages = {
        "/": (
            "text/html",
            '<main><h1>Home</h1><a href="/guide">Guide</a> <a href="/private/x">P</a> <a href="https://other.example/">X</a></main>',
        ),
        "/guide": (
            "text/html",
            '<main><h1>Guide</h1><p>Steps.</p><a href="/guide/deep">Deep</a><a href="/files/a.pdf">PDF</a></main>',
        ),
        "/guide/deep": ("text/html", "<main><h1>Deep</h1><p>Deep page.</p></main>"),
        "/private/x": ("text/html", "<main>secret</main>"),
        "/files/a.pdf": ("application/pdf", "%PDF-1.4 fake"),
        "/sitemap.xml": (
            "application/xml",
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://docs.example.com/orphan</loc></url></urlset>',
        ),
        "/orphan": ("text/html", "<main><h1>Orphan</h1><p>Only in the sitemap.</p></main>"),
    }
    return web


async def collect(connector: Any, ctx: Context, config: dict[str, Any]) -> list[Item]:
    return [i async for i in connector.discover(ctx, config)]


async def test_crawler_follows_links_robots_hosts_and_sitemaps(tmp_path: Path) -> None:
    web = site()
    ctx = context(tmp_path, web)
    items = await collect(
        WebCrawler(),
        ctx,
        {
            "start_urls": ["https://docs.example.com/"],
            "sitemap_urls": ["https://docs.example.com/sitemap.xml"],
        },
    )
    uris = sorted(i.uri for i in items)
    assert uris == [
        "https://docs.example.com/",
        "https://docs.example.com/files/a.pdf",
        "https://docs.example.com/guide",
        "https://docs.example.com/guide/deep",
        "https://docs.example.com/orphan",
    ]
    assert "/private/x" not in web.requests  # robots.txt disallows it
    # Pages fetched during discovery are reused, not downloaded again.
    before = len(web.requests)
    content = await WebCrawler().fetch(ctx, {}, Item(uri="https://docs.example.com/guide"), None)
    assert b"Steps." in content.data
    assert len(web.requests) == before


async def test_crawler_filters_depth_and_limits(tmp_path: Path) -> None:
    ctx = context(tmp_path, site())
    items = await collect(
        WebCrawler(),
        ctx,
        {
            "start_urls": ["https://docs.example.com/"],
            "include": ["https://docs.example.com/guide*"],
            "max_depth": 1,
        },
    )
    assert [i.uri for i in items] == ["https://docs.example.com/guide"]
    limited = await collect(
        WebCrawler(),
        context(tmp_path / "b", site(), max_items=2),
        {"start_urls": ["https://docs.example.com/"]},
    )
    assert len(limited) == 2


async def test_crawler_conditional_fetch(tmp_path: Path) -> None:
    web = site()
    ctx = context(tmp_path, web)
    first = await WebCrawler().fetch(ctx, {}, Item(uri="https://docs.example.com/orphan"), None)
    fresh = context(tmp_path / "other-run", web)
    again = await WebCrawler().fetch(
        fresh, {}, Item(uri="https://docs.example.com/orphan"), first.version
    )
    assert again.not_modified


async def test_crawler_refuses_internal_start_urls(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    with pytest.raises(FetchBlocked):
        await ctx.check_host("http://intranet.example.com/")


async def test_s3_connector(tmp_path: Path) -> None:
    listing = b"""<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>
      <Contents><Key>kb/a.md</Key><Size>12</Size><ETag>"e1"</ETag><LastModified>x</LastModified></Contents>
      <Contents><Key>kb/folder/</Key><Size>0</Size><ETag>"e0"</ETag><LastModified>x</LastModified></Contents>
      <Contents><Key>kb/skip.bin</Key><Size>5</Size><ETag>"e2"</ETag><LastModified>x</LastModified></Contents>
    </ListBucketResult>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        if request.url.params.get("list-type") == "2":
            return httpx.Response(200, content=listing)
        return httpx.Response(200, content=b"# A\n\nText.")

    web = FakeWeb()
    creds = {f"{TENANT}/kb": {"access_key": "ak", "secret_key": "sk"}}
    ctx = context(tmp_path, web, handler, credentials=creds)
    config = {
        "endpoint": "https://93.184.216.34",
        "bucket": "docs",
        "prefix": "kb/",
        "credentials_ref": "kb",
        "exclude": ["*.bin"],
    }
    items = await collect(S3Connector(), ctx, config)
    assert [(i.uri, i.version) for i in items] == [("s3://docs/kb/a.md", "e1")]
    content = await S3Connector().fetch(ctx, config, items[0], None)
    assert content.data == b"# A\n\nText."
    with pytest.raises(MissingCredentials):
        await collect(S3Connector(), context(tmp_path, web, handler), config)
    with pytest.raises(FetchBlocked):
        await collect(S3Connector(), ctx, {**config, "endpoint": "http://10.0.0.1"})


def _repo(path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)  # noqa: S603, S607

    path.mkdir(parents=True)
    git("init", "-q", "-b", "main")
    (path / "docs").mkdir()
    (path / "docs" / "intro.md").write_text("# Intro\n\nHello.")
    (path / "src.py").write_text("print('code')")
    (path / "link.md").symlink_to("/etc/hostname")
    git("add", "-A")
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")


async def test_git_listing_and_fetch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)

    class LocalGit(GitConnector):
        async def _checkout(self, ctx: Any, config: Any) -> Path:
            return repo

        async def _git(self, ctx: Any, config: Any, *args: str, cwd: str | None = None) -> str:
            proc = await asyncio.create_subprocess_exec(
                "git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE
            )
            out, _ = await proc.communicate()
            return out.decode()

    ctx = context(tmp_path)
    config = {"url": "https://git.example.com/org/docs.git"}
    items = await collect(LocalGit(), ctx, config)
    assert [i.title for i in items] == ["docs/intro.md"]  # code and symlinks are skipped
    content = await LocalGit().fetch(ctx, config, items[0], None)
    assert content.data.startswith(b"# Intro")
    with pytest.raises(ValueError, match="escapes"):
        await LocalGit().fetch(ctx, config, Item(uri="x", title="../../etc/passwd"), None)


async def test_git_command_is_pinned_and_keeps_secrets_out_of_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def fake_exec(*args: str, **kwargs: Any) -> Proc:
        seen["args"], seen["env"] = args, kwargs["env"]
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    web = FakeWeb()

    async def resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.40"]

    ctx = context(tmp_path, web, credentials={f"{TENANT}/gh": {"token": "s3cr3t-token"}})
    ctx.http = SafeFetcher(FetchPolicy(), resolver=resolve)
    await GitConnector()._git(
        ctx, {"url": "https://git.example.com/r.git", "credentials_ref": "gh"}, "ls-remote"
    )
    env = seen["env"]
    config = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert config["http.curloptResolve"] == "git.example.com:443:93.184.216.40"
    assert config["protocol.allow"] == "never"
    assert config["http.extraHeader"].startswith("Authorization: Basic ")
    assert not any("s3cr3t" in a or "Basic" in a for a in seen["args"])


def test_plugins_are_discovered_from_entry_points_and_validated() -> None:
    registry = Registry()
    names = registry.discover(
        eps=[
            EntryPoint("builtin", "nexiqon_ingestion.plugins:builtin", "nexiqon.plugins"),
            EntryPoint("sample", "nexiqon_ingestion.testing:sample_plugins", "nexiqon.plugins"),
        ]
    )
    assert "sample" in names
    assert "web" in names
    assert registry.get(PluginKind.CONNECTOR, "sample").manifest.title == "Sample"
    assert registry.validate_config(PluginKind.CONNECTOR, "sample", {"count": 2}) == []
    errors = registry.validate_config(PluginKind.CONNECTOR, "sample", {"count": 9, "x": 1})
    assert len(errors) == 2
    with pytest.raises(PluginError, match="duplicate"):
        registry.discover(
            eps=[EntryPoint("again", "nexiqon_ingestion.testing:sample_plugins", "nexiqon.plugins")]
        )
    gallery = [m.name for m in registry.manifests(PluginKind.CONNECTOR)]
    assert gallery == ["git", "s3", "sample", "upload", "web"]
