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
