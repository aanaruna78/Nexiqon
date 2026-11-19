from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol

from nexiqon_sdk.manifest import Manifest
from nexiqon_sdk.types import (
    Block,
    ChunkDraft,
    Content,
    EvalCase,
    EvalObservation,
    Item,
    ParsedDocument,
    Score,
)


class FetchResponse(Protocol):
    url: str
    status: int
    content: bytes
    headers: dict[str, str]


class HttpFetcher(Protocol):
    """SSRF-safe HTTP client supplied by the platform. Plugins must not open their own sockets."""

    async def get(self, url: str, headers: dict[str, str] | None = None) -> FetchResponse: ...


class ConnectorContext(Protocol):
    http: HttpFetcher
    max_items: int
    max_bytes: int

    async def read_upload(self, key: str) -> bytes: ...

    async def check_host(self, url: str) -> str:
        """Validate a URL's host like the fetcher does; returns the pinned address."""
        ...

    def workdir(self, name: str) -> str:
        """A private scratch directory for this run (may be empty on another worker)."""
        ...


class Connector(Protocol):
    manifest: Manifest

    def discover(self, ctx: ConnectorContext, config: Mapping[str, Any]) -> AsyncIterator[Item]: ...

    async def fetch(
        self,
        ctx: ConnectorContext,
        config: Mapping[str, Any],
        item: Item,
        previous_version: str | None,
    ) -> Content: ...


class Parser(Protocol):
    manifest: Manifest

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument: ...


class Chunker(Protocol):
    manifest: Manifest
    # True: the platform splits by headings first and chunks each section (document tree).
    uses_headings: bool

    def chunk(self, blocks: list[Block], options: Mapping[str, Any]) -> list[ChunkDraft]: ...


class Evaluator(Protocol):
    """Scores one evaluation case (QA-01). Deterministic evaluators need nothing else; ones that
    ask a model use the platform's model gateway through ``judge`` (never a vendor SDK)."""

    manifest: Manifest

    def applies(self, case: EvalCase) -> bool:
        """False when this evaluator has nothing to say about the case (e.g. no expected source)."""
        ...

    async def score(
        self, case: EvalCase, seen: EvalObservation, config: Mapping[str, Any]
    ) -> Score: ...
