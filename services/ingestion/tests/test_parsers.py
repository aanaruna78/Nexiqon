"""Parser golden tests (IN-06): block kinds, heading levels, page numbers, titles."""

from __future__ import annotations

import json

import pytest

from nexiqon_ingestion.plugins.parsers import (
    CsvParser,
    DocxParser,
    HtmlParser,
    JsonParser,
    MarkdownParser,
    PdfParser,
    TextParser,
)
from nexiqon_sdk import Registry

from .docs import HTML, MARKDOWN, docx, pdf


def shape(doc: object) -> list[tuple[str, int, str]]:
    return [(b.kind, b.level, b.text[:30]) for b in doc.blocks]  # type: ignore[attr-defined]


def test_markdown() -> None:
    doc = MarkdownParser().parse(MARKDOWN.encode(), "text/markdown", "guide.md")
    assert doc.title == "Platform Guide"
    assert shape(doc) == [
        ("heading", 1, "Platform Guide"),
        ("paragraph", 0, "Intro paragraph before any sect"[:30]),
        ("heading", 2, "Getting started"),
        ("paragraph", 0, "Install the agent. Then config"),
        ("list", 0, "- step one\n- step two"),
        ("heading", 3, "Requirements"),
        ("table", 0, "| Item | Value |\n|------|------"[:30]),
        ("heading", 2, "Empty section"),
        ("heading", 2, "Operations"),
        ("code", 0, "make run"),
        ("paragraph", 0, "Run it daily."),
    ]


def test_html_keeps_main_content_only() -> None:
    doc = HtmlParser().parse(HTML.encode(), "text/html", "https://x/ops")
    assert doc.title == "Operations Handbook"
    assert doc.language == "en"
    text = " ".join(b.text for b in doc.blocks)
    assert "tracking" not in text
    assert "Home" not in text
    assert "Copyright" not in text
    assert shape(doc) == [
        ("heading", 1, "Operations Handbook"),
        ("paragraph", 0, "Welcome to the handbook."),
        ("heading", 2, "Backups"),
        ("paragraph", 0, "Backups run nightly."),
        ("list", 0, "- Daily\n- Weekly"),
        ("heading", 2, "Restores"),
        ("table", 0, "Step | Time\nRequest | 1h"),
        ("code", 0, "restore --all"),
    ]


def test_pdf_pages_and_outline() -> None:
    data = pdf(
        ["Overview of the system.\nIt has parts.", "Setup steps here."],
        outline=[("Overview", 0), ("Setup", 1)],
    )
    doc = PdfParser().parse(data, "application/pdf", "manual.pdf")
    assert [(b.kind, b.text, b.page) for b in doc.blocks] == [
        ("heading", "Overview", 1),
        ("paragraph", "Overview of the system.\nIt has parts.", 1),
        ("heading", "Setup", 2),
        ("paragraph", "Setup steps here.", 2),
    ]


def test_pdf_without_outline_keeps_pages() -> None:
    doc = PdfParser().parse(pdf(["Page one text.", "Page two text."]), "application/pdf", "x.pdf")
    assert [(b.kind, b.page) for b in doc.blocks] == [("paragraph", 1), ("paragraph", 2)]


def test_docx() -> None:
    doc = DocxParser().parse(docx(), "application/octet-stream", "policy.docx")
    assert doc.title == "Policy Manual"
    assert shape(doc) == [
        ("heading", 1, "Policy Manual"),
        ("paragraph", 0, "Scope of this manual."),
        ("heading", 2, "Access"),
        ("paragraph", 0, "Access is granted by administr"),
        ("list", 0, "- first rule\n- second rule"),
        ("table", 0, "Role | Rights\nAdmin | All"),
    ]


def test_text_csv_json() -> None:
    assert [
        b.text for b in TextParser().parse(b"one\n\n\ntwo  words", "text/plain", "a.txt").blocks
    ] == ["one", "two words"]
    rows = CsvParser().parse(b"name,role\nAda,admin\nLin,\n", "text/csv", "people.csv").blocks
    assert [b.text for b in rows] == ["name: Ada; role: admin", "name: Lin"]
    data = json.dumps([{"id": 1, "tags": ["a", "b"], "meta": {"owner": "x"}}]).encode()
    blocks = JsonParser().parse(data, "application/json", "items.json").blocks
    assert blocks[0].text == "id: 1\ntags: a, b\nmeta.owner: x"


def test_registry_picks_parser_by_type_then_extension() -> None:
    registry = Registry()
    registry.discover()
    assert registry.parser_for("text/html; charset=utf-8", "x").manifest.name == "html"
    assert registry.parser_for("application/octet-stream", "Report.PDF").manifest.name == "pdf"
    assert registry.parser_for("application/zip", "a.zip") is None


def test_broken_pdf_raises() -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011 - pypdf raises several types
        PdfParser().parse(b"%PDF-1.4 garbage", "application/pdf", "bad.pdf")
