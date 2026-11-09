"""Answer contract and citation verification (RT-03).

An answer cites passages with markers like ``[1]``. Verification is deterministic and cheap:

* a citation to a passage the caller cannot see (or that does not exist) is fabricated: removed;
* an optional verbatim ``quote`` must occur in the passage (whitespace/case-insensitive);
* every sentence carrying a marker must be lexically supported by its cited passages (share of the
  sentence's content words found there >= ``min_support``); unsupported markers are removed.

If no valid citation remains, the caller should abstain (grounded answers must cite sources).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from nexiqon_retrieval.search import STOP, TERM

MARKER = re.compile(r"\[(\w{1,8})\]")
SENTENCE_SPLIT = re.compile(
    "(?<=[.!?" + "".join(map(chr, (0x3002, 0xFF01, 0xFF1F, 0x061F))) + r"])(\s+)"
)
SENTENCE = re.compile("(?<=[.!?\\u3002\\uff01\\uff1f\\u061f])\\s+")


@dataclass
class Citation:
    marker: str
    passage_id: uuid.UUID
    quote: str | None = None


@dataclass
class Removed:
    marker: str
    reason: str  # unknown_passage | quote_not_found | unsupported | not_referenced


@dataclass
class Verification:
    answer: str
    citations: list[Citation]
    removed: list[Removed] = field(default_factory=list)
    supported_sentences: int = 0
    cited_sentences: int = 0

    @property
    def abstain(self) -> bool:
        return not self.citations


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _content(text: str) -> set[str]:
    return {
        w for w in TERM.findall(text.lower()) if len(w) > 2 and w not in STOP and not w.isdigit()
    }


def verify(
    answer: str, citations: list[Citation], passages: dict[uuid.UUID, str], min_support: float
) -> Verification:
    removed: list[Removed] = []
    valid: dict[str, list[Citation]] = {}
    for c in citations:
        text = passages.get(c.passage_id)
        if text is None:
            removed.append(Removed(c.marker, "unknown_passage"))
        elif c.quote and _norm(c.quote) not in _norm(text):
            removed.append(Removed(c.marker, "quote_not_found"))
        else:
            valid.setdefault(c.marker, []).append(c)

    # Each sentence is judged on its own: a marker supported in one sentence does not validate
    # the same marker in another (QA2-05). Unsupported sentences lose their markers.
    supported_markers: set[str] = set()
    cited = supported = 0
    pieces: list[str] = []
    for index, piece in enumerate(SENTENCE_SPLIT.split(answer)):
        if index % 2:  # whitespace between sentences
            pieces.append(piece)
            continue
        markers = [m for m in MARKER.findall(piece) if m in valid]
        keep_here: set[str] = set()
        if markers:
            cited += 1
            words = _content(MARKER.sub("", piece))
            evidence = set().union(
                *(_content(passages[c.passage_id]) for m in markers for c in valid[m])
            )
            share = len(words & evidence) / len(words) if words else 1.0
            if share >= min_support:
                supported += 1
                keep_here = set(markers)
                supported_markers.update(markers)
            else:
                removed.extend(Removed(m, "unsupported") for m in dict.fromkeys(markers))

        def strip(match: re.Match[str], keep: set[str] = keep_here) -> str:
            return match.group(0) if match.group(1) in keep else ""

        pieces.append(MARKER.sub(strip, piece))
    in_text = set(MARKER.findall(answer))
    for marker in sorted(set(valid) - in_text):
        removed.append(Removed(marker, "not_referenced"))
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", "".join(pieces)).strip()
    kept = [c for m in sorted(supported_markers) for c in valid[m]]
    return Verification(cleaned, kept, removed, supported, cited)
