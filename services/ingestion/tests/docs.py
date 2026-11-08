"""Sample documents built in code (no binary fixtures in the repo)."""

from __future__ import annotations

import io

MARKDOWN = """---
title: Platform Guide
---
# Platform Guide

Intro paragraph before any section.

## Getting started

Install the agent. Then configure it.

- step one
- step two

### Requirements

| Item | Value |
|------|-------|
| CPU  | 2     |

## Empty section

## Operations

```bash
make run
```

Run it daily.
"""

HTML = """<!doctype html><html lang="en"><head><title>Operations Handbook</title>
<script>var tracking = 1;</script><style>p{}</style></head><body>
<nav><a href="/">Home</a> <a href="/guide">Guide</a></nav>
<main><h1>Operations Handbook</h1><p>Welcome to the handbook.</p>
<h2>Backups</h2><p>Backups run nightly.</p><ul><li>Daily</li><li>Weekly</li></ul>
<h2>Restores</h2><table><tr><th>Step</th><th>Time</th></tr><tr><td>Request</td><td>1h</td></tr></table>
<pre>restore --all</pre></main><footer>Copyright</footer></body></html>"""


def pdf(pages: list[str], outline: list[tuple[str, int]] | None = None) -> bytes:
    """A real text PDF (Helvetica), optionally with bookmarks (title, 0-based page)."""
    objects: list[bytes] = []
    kids = []
    n_pages = len(pages)
    # 1 document root, 2 pages, 3 font, then (page, content) pairs
    for i, text in enumerate(pages):
        page_obj, content_obj = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_obj} 0 R")
        lines = "".join(
            f"BT /F1 12 Tf 72 {720 - 20 * j} Td ({line}) Tj ET\n"
            for j, line in enumerate(text.split("\n"))
        ).encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(lines) + lines + b"endstream")
    head = [
        b"<< /Type /Catalog /Pages 2 0 R >>",  # arch: allow (PDF syntax)
        f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n_pages} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    all_objects = head + objects
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(all_objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(all_objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(all_objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    data = out.getvalue()
    if not outline:
        return data
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    for title, page in outline:
        writer.add_outline_item(title, page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def docx() -> bytes:
    import docx as python_docx

    d = python_docx.Document()
    d.core_properties.title = "Policy Manual"
    d.add_heading("Policy Manual", level=1)
    d.add_paragraph("Scope of this manual.")
    d.add_heading("Access", level=2)
    d.add_paragraph("Access is granted by administrators.")
    d.add_paragraph("first rule", style="List Bullet")
    d.add_paragraph("second rule", style="List Bullet")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Role", "Rights"
    table.cell(1, 0).text, table.cell(1, 1).text = "Admin", "All"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
