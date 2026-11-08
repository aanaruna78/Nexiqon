"""Document tree builder (IN-08): document > section > ... > chunk, with ltree paths.

Paths use zero-padded labels shared by sections and chunks (``d.s0001.c0002``), so sorting by path
gives reading order. Node ids are derived from (document, version, path): retrying an ingestion
produces the same ids, and a new version produces new ones.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from nexiqon_sdk import Block, Chunker, ParsedDocument


@dataclass
class TreeNode:
    id: uuid.UUID
    parent_id: uuid.UUID | None
    path: str
    kind: str
    ordinal: int
    title: str | None
    heading_path: list[str]
    text: str = ""
    page_start: int | None = None
    page_end: int | None = None
    token_count: int = 0
    children: list[TreeNode] = field(default_factory=list)
    level: int = 0


def build_tree(
    document_id: uuid.UUID,
    version: int,
    parsed: ParsedDocument,
    chunker: Chunker,
    options: Mapping[str, Any],
    fallback_title: str,
) -> list[TreeNode]:
    """Return nodes in reading order (root first). Empty sections are dropped."""

    def make(
        parent: TreeNode | None, kind: str, label: str, title: str | None, heading_path: list[str]
    ) -> TreeNode:
        ordinal = len(parent.children) + 1 if parent else 0
        path = f"{parent.path}.{label}{ordinal:04d}" if parent else "d"
        node = TreeNode(
            id=uuid.uuid5(document_id, f"{version}:{path}"),
            parent_id=parent.id if parent else None,
            path=path,
            kind=kind,
            ordinal=ordinal,
            title=title,
            heading_path=heading_path,
        )
        if parent:
            parent.children.append(node)
        return node

    root = make(None, "document", "d", parsed.title or fallback_title, [])
    stack: list[TreeNode] = [root]
    pending: list[Block] = []

    def flush() -> None:
        if not pending:
            return
        owner = stack[-1]
        for draft in chunker.chunk(list(pending), options):
            chunk = make(owner, "chunk", "c", None, list(owner.heading_path))
            chunk.text, chunk.token_count = draft.text, draft.token_count
            chunk.page_start, chunk.page_end = draft.page_start, draft.page_end
        pending.clear()

    for block in parsed.blocks:
        if block.kind == "heading" and chunker.uses_headings:
            flush()
            if block.level == 1 and not root.children and block.text == parsed.title:
                root.title = block.text  # the document's own title, not a section
                continue
            while len(stack) > 1 and stack[-1].level >= block.level:
                stack.pop()
            parent = stack[-1]
            section = make(parent, "section", "s", block.text, [*parent.heading_path, block.text])
            section.level = block.level
            section.page_start = block.page
            stack.append(section)
        elif block.kind == "heading":
            pending.append(Block("paragraph", block.text, page=block.page))
        else:
            pending.append(block)
    flush()

    def finish(node: TreeNode) -> bool:
        """Drop empty sections; roll page ranges and token counts up. True if node has content."""
        node.children = [c for c in node.children if finish(c)]
        if node.kind != "chunk":
            pages = [p for c in node.children for p in (c.page_start, c.page_end) if p is not None]
            if pages:
                node.page_start, node.page_end = min(pages), max(pages)
            node.token_count = sum(c.token_count for c in node.children)
        return node.kind == "chunk" or bool(node.children) or node is root

    finish(root)
    out: list[TreeNode] = []

    def walk(node: TreeNode) -> None:
        out.append(node)
        for child in node.children:
            walk(child)

    walk(root)
    # Ordinals and paths were assigned before pruning; renumber so paths stay dense and ordered.
    return _renumber(document_id, version, out)


def _renumber(document_id: uuid.UUID, version: int, nodes: list[TreeNode]) -> list[TreeNode]:
    root = nodes[0]
    mapping: dict[uuid.UUID, uuid.UUID] = {}

    def visit(node: TreeNode, path: str, parent_id: uuid.UUID | None) -> None:
        new_id = uuid.uuid5(document_id, f"{version}:{path}")
        mapping[node.id] = new_id
        node.id, node.path, node.parent_id = new_id, path, parent_id
        for i, child in enumerate(node.children, start=1):
            child.ordinal = i
            visit(child, f"{path}.{'c' if child.kind == 'chunk' else 's'}{i:04d}", new_id)

    visit(root, "d", None)
    return nodes


def embedding_text(document_title: str | None, node: TreeNode) -> str:
    """Contextual embedding input: where the chunk sits, then what it says."""
    context = " > ".join([t for t in [document_title, *node.heading_path] if t])
    return f"{context}\n\n{node.text}" if context else node.text
