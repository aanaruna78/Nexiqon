"""Prompt-injection defences (AG-03). Layers, none of which trusts the model to behave:

* input: blocked topics from the pack get a fixed refusal before any model call; instruction-like
  user text is flagged on the trace (the system prompt already says user text is data);
* sources: instruction-like lines inside retrieved passages and tool results are replaced before
  they reach the model, so a poisoned document cannot steer the answer;
* output: whatever the model wrote, images are removed (no exfiltration through image URLs), links
  survive only when they point at a cited source, raw HTML is stripped, and an answer that repeats
  the system prompt is withheld.

The red-team set in each pack (``eval/redteam.yaml``) runs these against a model that obeys every
injected instruction.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# Phrases that address the model rather than inform the reader. Kept short and generic.
INSTRUCTION = re.compile(
    r"(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+|your\s+)?"
    r"(previous|prior|above|earlier|system|safety)?\s*(instructions|rules|prompts?|guidelines)"
    r"|(reveal|print|show|repeat|output)\s+(me\s+)?(your|the)\s+(system\s+prompt|instructions|hidden\s+prompt)"
    r"|you\s+are\s+now\s+|act\s+as\s+(an?\s+)?(unrestricted|jailbroken|developer\s+mode)"
    r"|new\s+instructions\s*:|^\s*(system|assistant)\s*:"
    r"|(tenant|tenant_id|x-nexiqon-context)\s*[=:]\s*\S+",
    re.IGNORECASE | re.MULTILINE,
)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>", re.IGNORECASE)
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)[^)]*\)")
BARE_URL = re.compile(r"(?<![(\w])https?://[^\s)\]>]+", re.IGNORECASE)
TAG = re.compile(r"</?[a-zA-Z][^>]*>")
WORD = re.compile(r"\w+", re.UNICODE)
REMOVED = "[removed: instruction-like text]"


def flags_instructions(text: str) -> bool:
    return bool(INSTRUCTION.search(text or ""))


def neutralise(text: str) -> tuple[str, int]:
    """Replace instruction-like lines in source text; returns the text and how many were hit."""
    hits = 0
    lines = []
    for line in (text or "").splitlines():
        if INSTRUCTION.search(line):
            hits += 1
            lines.append(REMOVED)
        else:
            lines.append(line)
    return "\n".join(lines), hits


def _terms(text: str) -> set[str]:
    return {w.strip("'") for w in WORD.findall(text.lower()) if len(w) > 2}


def blocked_topic(question: str, topics: Iterable[str]) -> str | None:
    """A topic matches when every meaningful word of it (or its stem) appears in the question."""
    words = _terms(question)
    stems = {w[:5] for w in words}
    for topic in topics:
        needed = _terms(str(topic))
        if needed and all(w in words or w[:5] in stems for w in needed):
            return str(topic)
    return None


@dataclass
class OutputCheck:
    text: str
    removed: list[str] = field(default_factory=list)
    leaked: bool = False


def _shingles(text: str, size: int = 8) -> set[tuple[str, ...]]:
    words = WORD.findall(text.lower())
    return {tuple(words[i : i + size]) for i in range(max(len(words) - size + 1, 0))}


def check_output(text: str, *, allowed_urls: Iterable[str], system_prompt: str) -> OutputCheck:
    allowed = {u.rstrip("/") for u in allowed_urls if u}
    removed: list[str] = []

    def image(m: re.Match[str]) -> str:
        removed.append("image")
        return ""

    def link(m: re.Match[str]) -> str:
        if m.group(2).rstrip("/") in allowed:
            return m.group(0)
        removed.append("link")
        return m.group(1)

    def bare(m: re.Match[str]) -> str:
        if m.group(0).rstrip("/.,;") in allowed:
            return m.group(0)
        removed.append("link")
        return "[link removed]"

    def tag(m: re.Match[str]) -> str:
        removed.append("html")
        return ""

    out = IMAGE.sub(image, text)
    out = LINK.sub(link, out)
    out = BARE_URL.sub(bare, out)
    out = TAG.sub(tag, out)
    prompt = _shingles(system_prompt)
    leaked = bool(prompt) and len(prompt & _shingles(out)) >= 2
    return OutputCheck(text=re.sub(r"[ \t]{2,}", " ", out).strip(), removed=removed, leaked=leaked)
