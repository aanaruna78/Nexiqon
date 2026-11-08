"""Built-in chunkers: heading-aware (default, builds the document tree) and fixed token windows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from nexiqon_sdk import Block, ChunkDraft, Manifest, PluginKind, estimate_tokens

SENTENCE = re.compile("(?<=[.!?\u3002\uff01\uff1f])\\s+")  # also CJK sentence ends
OPTIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "max_tokens": {"type": "integer", "minimum": 50, "maximum": 4000},
        "overlap_tokens": {"type": "integer", "minimum": 0, "maximum": 1000},
    },
}


def _pieces(block: Block, max_tokens: int) -> list[str]:
    """Split one oversized block by sentences, then by words, so no piece exceeds the limit."""
    if estimate_tokens(block.text) <= max_tokens:
        return [block.text]
    out: list[str] = []
    current = ""
    for sentence in (
        SENTENCE.split(block.text) if block.kind == "paragraph" else block.text.split("\n")
    ):
        candidate = (
            f"{current} {sentence}".strip()
            if block.kind == "paragraph"
            else f"{current}\n{sentence}".strip("\n")
        )
        if estimate_tokens(candidate) <= max_tokens:
            current = candidate
            continue
        if current:
            out.append(current)
        if estimate_tokens(sentence) <= max_tokens:
            current = sentence
        else:  # a single huge sentence/line: split at word boundaries
            words, current = _words(sentence, max_tokens)
            out.extend(words)
    if current:
        out.append(current)
    return out


def _words(text: str, max_tokens: int) -> tuple[list[str], str]:
    """Windows of whole words within the limit; a single overlong word is cut by characters.
    Returns (full windows, the last partial window)."""
    size = max_tokens * 4
    windows: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > size:  # e.g. a long URL or base64 blob
            if current:
                windows.append(current)
                current = ""
            windows.append(word[:size])
            word = word[size:]
        candidate = f"{current} {word}".strip()
        if estimate_tokens(candidate) <= max_tokens:
            current = candidate
        else:
            windows.append(current)
            current = word
    return windows, current


def _tail(text: str, tokens: int) -> str:
    if tokens <= 0:
        return ""
    tail = text[-tokens * 4 :]
    cut = tail.find(" ")
    return tail[cut + 1 :] if 0 <= cut < len(tail) - 1 else tail


def pack(blocks: list[Block], max_tokens: int, overlap_tokens: int) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    parts: list[str] = []
    pages: list[int] = []

    def flush() -> None:
        if not parts:
            return
        text = "\n\n".join(parts)
        chunks.append(
            ChunkDraft(
                text,
                estimate_tokens(text),
                min(pages) if pages else None,
                max(pages) if pages else None,
            )
        )

    for block in blocks:
        for piece in _pieces(block, max_tokens):
            candidate = "\n\n".join([*parts, piece])
            if parts and estimate_tokens(candidate) > max_tokens:
                flush()
                overlap = _tail(chunks[-1].text, overlap_tokens)
                parts, pages = (
                    (
                        [overlap]
                        if overlap and estimate_tokens(overlap + piece) <= max_tokens
                        else []
                    ),
                    [],
                )
            parts.append(piece)
            if block.page is not None:
                pages.append(block.page)
    flush()
    return chunks


class HeadingAwareChunker:
    """Chunks within one section at a time, so a chunk never spans two headings."""

    manifest = Manifest(
        name="heading-aware",
        kind=PluginKind.CHUNKER,
        title="Heading-aware",
        description="Keeps sections together and builds the document tree for section-path citations.",
        config_schema=OPTIONS_SCHEMA,
        capabilities=["headings"],
    )
    uses_headings = True

    def chunk(self, blocks: list[Block], options: Mapping[str, Any]) -> list[ChunkDraft]:
        return pack(
            blocks, int(options.get("max_tokens", 400)), int(options.get("overlap_tokens", 40))
        )


class TokenChunker:
    manifest = Manifest(
        name="token",
        kind=PluginKind.CHUNKER,
        title="Fixed size",
        description="Equal-size windows ignoring headings (for unstructured text).",
        config_schema=OPTIONS_SCHEMA,
    )
    uses_headings = False

    def chunk(self, blocks: list[Block], options: Mapping[str, Any]) -> list[ChunkDraft]:
        flat = [Block("paragraph", b.text, page=b.page) for b in blocks]
        return pack(
            flat, int(options.get("max_tokens", 400)), int(options.get("overlap_tokens", 40))
        )


CHUNKERS = [HeadingAwareChunker(), TokenChunker()]
