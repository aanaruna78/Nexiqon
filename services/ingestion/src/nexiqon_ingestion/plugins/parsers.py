"""Built-in parsers: Markdown, HTML, plain text, PDF, DOCX, CSV and JSON (IN-06).

Every parser returns ordered blocks; headings carry levels, paged formats carry page numbers, so the
document tree and citations can point at "Section > Subsection, p.4".
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from nexiqon_sdk import Block, Manifest, ParsedDocument, PluginKind

MAX_TABLE_ROWS = 2000
WS = re.compile(r"[ \t\r\f\v]+")


def _clean(text: str) -> str:
    return "\n".join(WS.sub(" ", line).strip() for line in text.splitlines()).strip()


def _decode(data: bytes) -> str:
    for encoding in (
        ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",)
    ):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _paragraphs(text: str, page: int | None = None) -> list[Block]:
    return [
        Block("paragraph", _clean(p), page=page) for p in re.split(r"\n\s*\n", text) if _clean(p)
    ]


class MarkdownParser:
    manifest = Manifest(
        name="markdown",
        kind=PluginKind.PARSER,
        title="Markdown",
        description="Headings, paragraphs, lists, tables and code blocks.",
        media_types=["text/markdown", "text/x-markdown"],
        extensions=[".md", ".markdown", ".mdx"],
        capabilities=["headings"],
    )

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument:
        from markdown_it import MarkdownIt

        text = _decode(data)
        meta: dict[str, Any] = {}
        if text.startswith("---\n"):  # front matter: keep the title, drop the rest
            end = text.find("\n---", 4)
            if end != -1:
                for line in text[4:end].splitlines():
                    key, _, value = line.partition(":")
                    if key.strip() == "title":
                        meta["title"] = value.strip().strip("\"'")
                text = text[end + 4 :]
        tokens = MarkdownIt("commonmark").enable("table").parse(text)
        blocks: list[Block] = []
        i = 0
        lines = text.splitlines()
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == "heading_open":
                blocks.append(
                    Block("heading", _clean(tokens[i + 1].content), level=int(tok.tag[1]))
                )
                i += 3
                continue
            if tok.type in ("fence", "code_block"):
                blocks.append(Block("code", tok.content.rstrip()))
            elif tok.type in ("bullet_list_open", "ordered_list_open", "table_open") and tok.map:
                close = tok.type.replace("_open", "_close")
                depth, j = 0, i
                while j < len(tokens):
                    if tokens[j].type == tok.type:
                        depth += 1
                    elif tokens[j].type == close:
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                raw = "\n".join(lines[tok.map[0] : tok.map[1]])
                blocks.append(Block("table" if tok.type == "table_open" else "list", _clean(raw)))
                i = j + 1
                continue
            elif tok.type == "paragraph_open" and tokens[i + 1].content.strip():
                blocks.append(Block("paragraph", _clean(tokens[i + 1].content)))
            i += 1
        title = meta.get("title") or next(
            (b.text for b in blocks if b.kind == "heading" and b.level == 1), None
        )
        return ParsedDocument(title=title, blocks=blocks)


class HtmlParser:
    manifest = Manifest(
        name="html",
        kind=PluginKind.PARSER,
        title="HTML",
        description="Main page content; navigation, scripts and footers are dropped.",
        media_types=["text/html", "application/xhtml+xml"],
        extensions=[".html", ".htm"],
        capabilities=["headings"],
    )
    DROP = (
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "svg",
        "iframe",
        "template",
    )

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(data, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else None
        for tag in soup(self.DROP):
            tag.decompose()
        root = soup.find("main") or soup.find("article") or soup.body or soup
        blocks: list[Block] = []
        for el in root.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "p",
                "ul",
                "ol",
                "pre",
                "table",
                "blockquote",
                "dl",
            ]
        ):
            if el.find_parent(["ul", "ol", "table", "pre", "blockquote", "dl"]) is not None:
                continue  # nested inside a block we already take whole
            name = el.name
            if name.startswith("h") and len(name) == 2:
                text = el.get_text(" ", strip=True)
                if text:
                    blocks.append(Block("heading", text, level=int(name[1])))
            elif name in ("ul", "ol"):
                items = [li.get_text(" ", strip=True) for li in el.find_all("li")]
                blocks.append(Block("list", "\n".join(f"- {t}" for t in items if t)))
            elif name == "pre":
                blocks.append(Block("code", el.get_text().rstrip()))
            elif name == "table":
                rows = []
                for tr in el.find_all("tr")[:MAX_TABLE_ROWS]:
                    cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                    rows.append(" | ".join(cells))
                blocks.append(Block("table", "\n".join(rows)))
            else:
                text = el.get_text(" ", strip=True)
                if text:
                    blocks.append(Block("paragraph", text))
        blocks = [b for b in blocks if b.text]
        if not title:
            title = next((b.text for b in blocks if b.kind == "heading"), None)
        lang = soup.html.get("lang") if soup.html else None
        return ParsedDocument(title=title, blocks=blocks, language=str(lang) if lang else None)


class TextParser:
    manifest = Manifest(
        name="text",
        kind=PluginKind.PARSER,
        title="Plain text",
        media_types=["text/plain"],
        extensions=[".txt", ".text", ".log", ".rst"],
    )

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument:
        return ParsedDocument(title=None, blocks=_paragraphs(_decode(data)))


class PdfParser:
    manifest = Manifest(
        name="pdf",
        kind=PluginKind.PARSER,
        title="PDF",
        description="Text per page; the PDF outline (bookmarks) becomes headings. Scanned pages need OCR (not included).",
        media_types=["application/pdf"],
        extensions=[".pdf"],
        capabilities=["pages", "headings"],
    )

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("encrypted PDFs are not supported")
        # Outline entries: (page index, level, title), to insert headings at page starts.
        marks: dict[int, list[tuple[int, str]]] = {}

        def walk(items: list[Any], level: int) -> None:
            for item in items:
                if isinstance(item, list):
                    walk(item, level + 1)
                    continue
                try:
                    page = reader.get_destination_page_number(item)
                except Exception:  # noqa: S112 - malformed bookmarks are skipped
                    continue
                if page is None:
                    continue
                marks.setdefault(page, []).append((min(level, 6), str(item.title).strip()))

        try:
            walk(list(reader.outline), 1)
        except Exception:
            marks = {}
        blocks: list[Block] = []
        for index, page in enumerate(reader.pages):
            for level, title in marks.get(index, []):
                if title:
                    blocks.append(Block("heading", title, level=level, page=index + 1))
            blocks.extend(_paragraphs(page.extract_text() or "", page=index + 1))
        meta_title = reader.metadata.title if reader.metadata else None
        return ParsedDocument(title=str(meta_title) if meta_title else None, blocks=blocks)


class DocxParser:
    manifest = Manifest(
        name="docx",
        kind=PluginKind.PARSER,
        title="Word (DOCX)",
        media_types=["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
        extensions=[".docx"],
        capabilities=["headings"],
    )

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = docx.Document(io.BytesIO(data))
        blocks: list[Block] = []
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                text = _clean(item.text)
                if not text:
                    continue
                style = (item.style.name if item.style is not None else "") or ""
                if style == "Title":
                    blocks.append(Block("heading", text, level=1))
                elif style.startswith("Heading") and style[7:].strip().isdigit():
                    blocks.append(Block("heading", text, level=min(int(style[7:]), 6)))
                elif "List" in style:
                    blocks.append(Block("list", f"- {text}"))
                else:
                    blocks.append(Block("paragraph", text))
            elif isinstance(item, Table):
                rows = [
                    " | ".join(_clean(c.text) for c in row.cells)
                    for row in item.rows[:MAX_TABLE_ROWS]
                ]
                blocks.append(Block("table", "\n".join(rows)))
        title = document.core_properties.title or next(
            (b.text for b in blocks if b.kind == "heading"), None
        )
        return ParsedDocument(title=title or None, blocks=_merge_lists(blocks))


def _merge_lists(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for b in blocks:
        if b.kind == "list" and out and out[-1].kind == "list":
            out[-1] = Block("list", out[-1].text + "\n" + b.text, page=out[-1].page)
        else:
            out.append(b)
    return out


class CsvParser:
    manifest = Manifest(
        name="csv",
        kind=PluginKind.PARSER,
        title="CSV",
        description="Each row becomes a 'column: value' record.",
        media_types=["text/csv"],
        extensions=[".csv", ".tsv"],
    )

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument:
        text = _decode(data)
        dialect = csv.excel_tab if uri.lower().endswith(".tsv") else csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
        if not rows:
            return ParsedDocument(title=None, blocks=[])
        header, records = rows[0], rows[1 : MAX_TABLE_ROWS + 1]
        blocks = [
            Block(
                "paragraph",
                "; ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False) if v.strip()),
            )
            for row in records
        ]
        return ParsedDocument(title=None, blocks=[b for b in blocks if b.text])


class JsonParser:
    manifest = Manifest(
        name="json",
        kind=PluginKind.PARSER,
        title="JSON",
        description="Arrays of objects become records; other documents become 'key.path: value' lines.",
        media_types=["application/json"],
        extensions=[".json", ".jsonl"],
    )

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument:
        text = _decode(data)
        if uri.lower().endswith(".jsonl"):
            value: Any = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            value = json.loads(text)
        records = value if isinstance(value, list) else [value]
        blocks = [Block("paragraph", "\n".join(_flatten(r))) for r in records[:MAX_TABLE_ROWS]]
        return ParsedDocument(title=None, blocks=[b for b in blocks if b.text])


def _flatten(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        return [
            line
            for k, v in value.items()
            for line in _flatten(v, f"{prefix}.{k}" if prefix else str(k))
        ]
    if isinstance(value, list):
        if all(not isinstance(v, dict | list) for v in value):
            return [f"{prefix}: {', '.join(str(v) for v in value)}"] if value else []
        return [line for i, v in enumerate(value) for line in _flatten(v, f"{prefix}[{i}]")]
    if value is None or value == "":
        return []
    return [f"{prefix}: {value}" if prefix else str(value)]


PARSERS = [
    MarkdownParser(),
    HtmlParser(),
    TextParser(),
    PdfParser(),
    DocxParser(),
    CsvParser(),
    JsonParser(),
]
