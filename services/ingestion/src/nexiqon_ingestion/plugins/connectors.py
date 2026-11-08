"""Built-in source connectors: upload, web/sitemap crawler, S3-compatible bucket, Git (IN-03).

Connectors only use what the platform hands them in ``ctx``: the SSRF-safe fetcher, host checks,
operator-held credentials and a scratch directory. Change detection uses each source's own version
token (ETag, object ETag, git blob sha) and, failing that, a content hash.
"""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import hashlib
import os
import xml.etree.ElementTree as ET  # sitemap XML; expat does not resolve external entities
from collections import deque
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from nexiqon_ingestion.plugins.context import Context
from nexiqon_sdk import Content, Item, Manifest, PluginKind

GLOBS = {"type": "array", "items": {"type": "string", "maxLength": 300}, "maxItems": 50}


def _matches(value: str, include: list[str], exclude: list[str]) -> bool:
    if include and not any(fnmatch.fnmatch(value, g) for g in include):
        return False
    return not any(fnmatch.fnmatch(value, g) for g in exclude)


class UploadConnector:
    manifest = Manifest(
        name="upload",
        kind=PluginKind.CONNECTOR,
        title="File upload",
        description="Upload PDF, Word, Markdown, HTML, text, CSV or JSON files.",
        capabilities=["push"],
        icon="upload",
    )

    async def discover(self, ctx: Context, config: Mapping[str, Any]) -> AsyncIterator[Item]:
        return
        yield  # pragma: no cover - uploads are pushed, never discovered

    async def fetch(
        self, ctx: Context, config: Mapping[str, Any], item: Item, previous_version: str | None
    ) -> Content:
        data = await ctx.read_upload(str(item.metadata["blob_key"]))
        return Content(
            uri=item.uri, data=data, media_type=item.media_type or "application/octet-stream"
        )


# --------------------------------------------------------------------------- web crawler


class WebCrawler:
    manifest = Manifest(
        name="web",
        kind=PluginKind.CONNECTOR,
        title="Website",
        description="Crawl a documentation site or sitemap. Respects robots.txt; only changed pages are re-embedded.",
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["start_urls"],
            "properties": {
                "start_urls": {
                    "type": "array",
                    "items": {"type": "string", "format": "uri", "pattern": "^https?://"},
                    "minItems": 1,
                    "maxItems": 20,
                },
                "sitemap_urls": {
                    "type": "array",
                    "items": {"type": "string", "format": "uri", "pattern": "^https?://"},
                    "maxItems": 10,
                },
                "include": {
                    **GLOBS,
                    "description": "URL globs to keep, e.g. https://docs.example.com/guide/*",
                },
                "exclude": {**GLOBS, "description": "URL globs to skip"},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 200},
                "max_depth": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3},
                "same_host_only": {"type": "boolean", "default": True},
            },
        },
        capabilities=["discover", "incremental", "schedule"],
        icon="globe",
    )

    async def _allowed(self, ctx: Context, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        robots_cache: dict[str, RobotFileParser | None] = ctx.state.setdefault("robots", {})
        if origin not in robots_cache:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                res = await ctx.http.get(f"{origin}/robots.txt")
                if res.status == 200:
                    parser.parse(res.content.decode(errors="replace").splitlines())  # type: ignore[union-attr]
                elif 400 <= res.status < 500:
                    parser = None  # no robots.txt: everything allowed
                else:
                    parser.disallow_all = True  # type: ignore[union-attr]  # server error: be conservative
            except Exception:
                parser.disallow_all = True  # type: ignore[union-attr]
            robots_cache[origin] = parser
        robots = robots_cache[origin]
        return robots is None or robots.can_fetch(ctx.user_agent, url)

    async def _sitemap(self, ctx: Context, url: str, depth: int = 0) -> list[str]:
        try:
            res = await ctx.http.get(url)
            root = ET.fromstring(res.content)  # noqa: S314 - see module import note
        except Exception:
            return []
        locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
        if root.tag.endswith("sitemapindex") and depth < 2:
            nested: list[str] = []
            for loc in locs[:50]:
                nested += await self._sitemap(ctx, loc, depth + 1)
            return nested
        return locs

    async def discover(self, ctx: Context, config: Mapping[str, Any]) -> AsyncIterator[Item]:
        from bs4 import BeautifulSoup

        include, exclude = list(config.get("include", [])), list(config.get("exclude", []))
        max_pages = min(int(config.get("max_pages", 200)), ctx.max_items)
        max_depth = int(config.get("max_depth", 3))
        for start in [*config["start_urls"], *config.get("sitemap_urls", [])]:
            await ctx.check_host(start)  # a blocked start URL fails the run with a clear reason
        hosts = {urlsplit(u).netloc for u in config["start_urls"]}
        same_host = bool(config.get("same_host_only", True))
        queue: deque[tuple[str, int]] = deque((u, 0) for u in config["start_urls"])
        for sitemap in config.get("sitemap_urls", []):
            queue.extend((u, max_depth) for u in await self._sitemap(ctx, sitemap))
        seen: set[str] = set()
        found = 0
        while queue and found < max_pages:
            url, depth = queue.popleft()
            url = urldefrag(url).url
            if url in seen or urlsplit(url).scheme not in ("http", "https"):
                continue
            seen.add(url)
            if same_host and urlsplit(url).netloc not in hosts:
                continue
            if not _matches(url, include, exclude) and depth > 0:
                continue
            if not await self._allowed(ctx, url):
                continue
            try:
                res = await ctx.http.get(url)
            except Exception as exc:
                ctx.warn(url, str(exc))
                continue
            if res.status != 200:
                ctx.warn(url, f"HTTP {res.status}")
                continue
            media = res.headers.get("content-type", "").split(";")[0].strip().lower()
            if _matches(url, include, exclude):
                ctx.cache_put(url, res.content, media, res.headers.get("etag"))
                found += 1
                yield Item(
                    uri=url,
                    version=res.headers.get("etag"),
                    media_type=media,
                    size=len(res.content),
                )
            if media == "text/html" and depth < max_depth:
                soup = BeautifulSoup(res.content, "html.parser")
                for a in soup.find_all("a", href=True):
                    queue.append(
                        (
                            urljoin(res.url if res.url.startswith("http") else url, str(a["href"])),
                            depth + 1,
                        )
                    )

    async def fetch(
        self, ctx: Context, config: Mapping[str, Any], item: Item, previous_version: str | None
    ) -> Content:
        cached = ctx.cache_get(item.uri)
        if cached is not None:
            data, media, etag = cached
            return Content(uri=item.uri, data=data, media_type=media, version=etag)
        headers = {"if-none-match": previous_version} if previous_version else {}
        res = await ctx.http.get(item.uri, headers=headers)
        if res.status == 304:
            return Content(uri=item.uri, not_modified=True, version=previous_version)
        if res.status != 200:
            raise ValueError(f"HTTP {res.status}")
        media = res.headers.get("content-type", "").split(";")[0].strip().lower()
        return Content(
            uri=item.uri, data=res.content, media_type=media, version=res.headers.get("etag")
        )


# --------------------------------------------------------------------------- S3-compatible bucket


class S3Connector:
    manifest = Manifest(
        name="s3",
        kind=PluginKind.CONNECTOR,
        title="S3 bucket",
        description="Any S3-compatible bucket (AWS S3, DigitalOcean Spaces, MinIO, SeaweedFS).",
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["endpoint", "bucket", "credentials_ref"],
            "properties": {
                "endpoint": {"type": "string", "format": "uri", "pattern": "^https?://"},
                "region": {"type": "string", "default": "us-east-1"},
                "bucket": {"type": "string", "pattern": "^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"},
                "prefix": {"type": "string", "maxLength": 500, "default": ""},
                "include": GLOBS,
                "exclude": GLOBS,
                "credentials_ref": {
                    "type": "string",
                    "pattern": "^[a-z0-9][a-z0-9-]{1,62}$",
                    "description": "Name of credentials an operator stored for this tenant (never entered here)",
                },
            },
        },
        capabilities=["discover", "incremental", "schedule"],
        icon="bucket",
    )

    async def _client(self, ctx: Context, config: Mapping[str, Any]) -> Any:
        from nexiqon_core.adapters.s3 import S3Client

        await ctx.check_host(str(config["endpoint"]))
        creds = ctx.credentials(str(config["credentials_ref"]))
        return S3Client(
            str(config["endpoint"]),
            str(config.get("region", "us-east-1")),
            creds["access_key"],
            creds["secret_key"],
            transport=ctx.transport,
        )

    async def discover(self, ctx: Context, config: Mapping[str, Any]) -> AsyncIterator[Item]:
        client = await self._client(ctx, config)
        try:
            objects = await client.list_objects(
                str(config["bucket"]), str(config.get("prefix", "")), ctx.max_items
            )
        finally:
            await client.aclose()
        include, exclude = list(config.get("include", [])), list(config.get("exclude", []))
        for obj in objects:
            if (
                obj.key.endswith("/")
                or obj.size > ctx.max_bytes
                or not _matches(obj.key, include, exclude)
            ):
                continue
            yield Item(
                uri=f"s3://{config['bucket']}/{obj.key}",
                title=obj.key.rsplit("/", 1)[-1],
                version=obj.etag,
                size=obj.size,
            )

    async def fetch(
        self, ctx: Context, config: Mapping[str, Any], item: Item, previous_version: str | None
    ) -> Content:
        key = item.uri.split("/", 3)[3]
        client = await self._client(ctx, config)
        try:
            data = await client.get_object(str(config["bucket"]), key)
        finally:
            await client.aclose()
        return Content(
            uri=item.uri, data=data, media_type="application/octet-stream", version=item.version
        )


# --------------------------------------------------------------------------- Git repository


class GitConnector:
    manifest = Manifest(
        name="git",
        kind=PluginKind.CONNECTOR,
        title="Git repository",
        description="Docs from a Git repository over HTTPS (shallow clone of one branch).",
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "format": "uri", "pattern": "^https://"},
                "branch": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9._/-]{1,200}$",
                    "default": "main",
                },
                "include": {**GLOBS, "default": ["*.md", "*.mdx", "*.rst", "*.txt", "*.html"]},
                "exclude": GLOBS,
                "credentials_ref": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{1,62}$"},
            },
        },
        capabilities=["discover", "incremental", "schedule"],
        icon="git",
    )
    TIMEOUT = 180

    async def _git(
        self, ctx: Context, config: Mapping[str, Any], *args: str, cwd: str | None = None
    ) -> str:
        url = str(config["url"])
        host = urlsplit(url).hostname or ""
        address = await ctx.check_host(url)
        pinned = f"[{address}]" if ":" in address else address
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": ctx.workdir("git-home"),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ASKPASS": "/bin/false",
        }
        # Config through the environment, so credentials never appear in process arguments.
        settings = [
            ("protocol.allow", "never"),
            ("protocol.https.allow", "always"),
            ("http.followRedirects", "false"),
            ("http.curloptResolve", f"{host}:443:{pinned}"),  # connect only to the checked address
        ]
        if config.get("credentials_ref"):
            token = ctx.credentials(str(config["credentials_ref"]))["token"]
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            settings.append(("http.extraHeader", f"Authorization: Basic {basic}"))
        env["GIT_CONFIG_COUNT"] = str(len(settings))
        for i, (k, v) in enumerate(settings):
            env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = k, v
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(self.TIMEOUT):
                out, err = await proc.communicate()
        except TimeoutError:
            proc.kill()
            raise RuntimeError("git timed out") from None
        if proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {err.decode(errors='replace')[-300:]}")
        return out.decode(errors="replace")

    async def _checkout(self, ctx: Context, config: Mapping[str, Any]) -> Path:
        repo = Path(
            ctx.workdir("git-" + hashlib.sha256(str(config["url"]).encode()).hexdigest()[:16])
        )
        if not (repo / ".git").exists():
            await self._git(
                ctx,
                config,
                "clone", "--depth", "1", "--single-branch", "--no-tags",
                "--branch", str(config.get("branch", "main")),
                str(config["url"]), str(repo),
            )  # fmt: skip
        return repo

    async def discover(self, ctx: Context, config: Mapping[str, Any]) -> AsyncIterator[Item]:
        repo = await self._checkout(ctx, config)
        listing = await self._git(ctx, config, "ls-tree", "-r", "-l", "HEAD", cwd=str(repo))
        include = list(config.get("include", ["*.md", "*.mdx", "*.rst", "*.txt", "*.html"]))
        exclude = list(config.get("exclude", []))
        count = 0
        for line in listing.splitlines():
            meta, _, path = line.partition("\t")
            mode, kind, sha, size = meta.split()
            if (
                kind != "blob"
                or mode == "120000"
                or not size.isdigit()
                or int(size) > ctx.max_bytes
            ):
                continue  # skip symlinks, submodules and oversized files
            if not _matches(path, include, exclude):
                continue
            yield Item(
                uri=f"{config['url']}#{config.get('branch', 'main')}:{path}",
                title=path,
                version=sha,
                size=int(size),
            )
            count += 1
            if count >= ctx.max_items:
                return

    async def fetch(
        self, ctx: Context, config: Mapping[str, Any], item: Item, previous_version: str | None
    ) -> Content:
        repo = await self._checkout(ctx, config)
        path = (repo / str(item.title)).resolve()
        if repo.resolve() not in path.parents:
            raise ValueError("path escapes the repository")
        return Content(
            uri=item.uri,
            data=path.read_bytes(),
            media_type="application/octet-stream",
            version=item.version,
        )


CONNECTORS = [UploadConnector(), WebCrawler(), S3Connector(), GitConnector()]
