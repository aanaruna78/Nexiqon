from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

BlockKind = Literal["heading", "paragraph", "list", "table", "code"]


def estimate_tokens(text: str) -> int:
    """Model-neutral token estimate (about four characters per token)."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


@dataclass(frozen=True)
class Item:
    """Something a connector found: a page, file or object."""

    uri: str
    title: str | None = None
    # Change token from the source (ETag, git blob sha, object ETag...). None: compare content.
    version: str | None = None
    media_type: str | None = None
    size: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Content:
    uri: str
    data: bytes = b""
    media_type: str = "application/octet-stream"
    version: str | None = None
    not_modified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    level: int = 0  # heading level (1 = top)
    page: int | None = None  # 1-based page for paged formats


@dataclass(frozen=True)
class ParsedDocument:
    title: str | None
    blocks: list[Block]
    language: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    token_count: int
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class EvalCase:
    """A question with what a good answer looks like. Every expectation is optional."""

    question: str
    lang: str = "en"
    # The answer should rest on this document (file name or URI suffix) and section heading.
    expected_source: str | None = None
    expected_section: str | None = None
    # Phrases a correct answer contains (any one is enough), compared case-insensitively.
    expected_phrases: tuple[str, ...] = ()
    # The sources do not answer this: a good assistant says so instead of guessing.
    must_abstain: bool = False


@dataclass(frozen=True)
class EvalCitation:
    citation: str  # "Title > Heading" as shown to the reader
    source_uri: str | None = None


@dataclass(frozen=True)
class EvalObservation:
    """What the assistant did for one case."""

    answer: str
    abstained: bool
    citations: tuple[EvalCitation, ...] = ()
    kind: str | None = None  # grounded | smalltalk | blocked | withheld | unavailable | ...
    latency_ms: int = 0
    tokens: int = 0
    cost: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class Score:
    """0..1; ``passed`` decides the case. ``detail`` explains the score to a person."""

    value: float
    passed: bool
    detail: str = ""
