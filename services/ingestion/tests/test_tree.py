"""Document tree golden tests (IN-08)."""

from __future__ import annotations

import uuid

from nexiqon_ingestion.plugins.chunkers import HeadingAwareChunker, TokenChunker, pack
from nexiqon_ingestion.plugins.parsers import MarkdownParser, PdfParser
from nexiqon_ingestion.tree import build_tree, embedding_text
from nexiqon_sdk import Block

from .docs import MARKDOWN, pdf

DOC = uuid.UUID("00000000-0000-0000-0000-000000000001")
OPTIONS = {"max_tokens": 400, "overlap_tokens": 40}


def outline(nodes: list) -> list[tuple[str, str, str | None, list[str]]]:  # type: ignore[type-arg]
    return [(n.path, n.kind, n.title, n.heading_path) for n in nodes]


def test_markdown_tree() -> None:
    parsed = MarkdownParser().parse(MARKDOWN.encode(), "text/markdown", "guide.md")
    nodes = build_tree(DOC, 1, parsed, HeadingAwareChunker(), OPTIONS, "guide.md")
    assert outline(nodes) == [
        ("d", "document", "Platform Guide", []),
        ("d.c0001", "chunk", None, []),
        ("d.s0002", "section", "Getting started", ["Getting started"]),
        ("d.s0002.c0001", "chunk", None, ["Getting started"]),
        ("d.s0002.s0002", "section", "Requirements", ["Getting started", "Requirements"]),
        ("d.s0002.s0002.c0001", "chunk", None, ["Getting started", "Requirements"]),
        # "Empty section" has no content and is dropped
        ("d.s0003", "section", "Operations", ["Operations"]),
        ("d.s0003.c0001", "chunk", None, ["Operations"]),
    ]
    by_path = {n.path: n for n in nodes}
    assert by_path["d.s0002.c0001"].parent_id == by_path["d.s0002"].id
    assert (
        by_path["d.s0002.c0001"].text
        == "Install the agent. Then configure it.\n\n- step one\n- step two"
    )
    assert by_path["d"].token_count == sum(n.token_count for n in nodes if n.kind == "chunk")
    assert embedding_text("Platform Guide", by_path["d.s0002.s0002.c0001"]).startswith(
        "Platform Guide > Getting started > Requirements\n\n"
    )


def test_ids_are_stable_per_version() -> None:
    parsed = MarkdownParser().parse(MARKDOWN.encode(), "text/markdown", "guide.md")
    a = build_tree(DOC, 1, parsed, HeadingAwareChunker(), OPTIONS, "x")
    b = build_tree(DOC, 1, parsed, HeadingAwareChunker(), OPTIONS, "x")
    c = build_tree(DOC, 2, parsed, HeadingAwareChunker(), OPTIONS, "x")
    assert [n.id for n in a] == [n.id for n in b]
    assert not {n.id for n in a} & {n.id for n in c}


def test_pdf_tree_carries_pages() -> None:
    parsed = PdfParser().parse(
        pdf(["Alpha text.", "Beta text."], outline=[("Alpha", 0), ("Beta", 1)]),
        "application/pdf",
        "m.pdf",
    )
    nodes = build_tree(DOC, 1, parsed, HeadingAwareChunker(), OPTIONS, "m.pdf")
    sections = [(n.title, n.page_start, n.page_end) for n in nodes if n.kind == "section"]
    assert sections == [("Alpha", 1, 1), ("Beta", 2, 2)]
    assert nodes[0].title == "m.pdf"  # no PDF title metadata: falls back to the file name
    assert (nodes[0].page_start, nodes[0].page_end) == (1, 2)


def test_token_chunker_ignores_headings() -> None:
    parsed = MarkdownParser().parse(MARKDOWN.encode(), "text/markdown", "guide.md")
    nodes = build_tree(DOC, 1, parsed, TokenChunker(), {"max_tokens": 50, "overlap_tokens": 0}, "x")
    assert {n.kind for n in nodes} == {"document", "chunk"}
    assert all(n.token_count <= 50 for n in nodes if n.kind == "chunk")


def test_packing_respects_limits_and_overlap() -> None:
    long = " ".join(f"Sentence number {i} is here." for i in range(200))
    chunks = pack([Block("paragraph", long)], max_tokens=100, overlap_tokens=10)
    assert len(chunks) > 5
    assert all(c.token_count <= 100 for c in chunks)
    # overlap: each chunk starts with words from the end of the previous one
    assert chunks[1].text.split()[0] in chunks[0].text
    huge = pack([Block("code", "x" * 5000)], max_tokens=100, overlap_tokens=0)
    assert all(c.token_count <= 100 for c in huge)
    assert "".join(c.text for c in huge) == "x" * 5000
