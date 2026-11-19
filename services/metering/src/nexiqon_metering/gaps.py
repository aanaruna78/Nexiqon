"""Content-gap clustering (MT-02, UX G3): group the questions the assistant could not answer (or
handed to a person, or whose answer was rated unhelpful) into topics, so a content manager sees
"14 people asked how long backups are kept" instead of 14 separate rows.

Deterministic and model-free: TF-IDF over word tokens (any script, so Arabic works too) and a
greedy single pass that joins a question to the closest topic above a similarity threshold.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
# Words that say nothing about the topic (English, Spanish, French, German question words).
STOP = set(
    [
        "the",
        "and",
        "for",
        "you",
        "your",
        "are",
        "can",
        "how",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "does",
        "did",
        "not",
        "with",
        "this",
        "that",
        "from",
        "have",
        "has",
        "had",
        "was",
        "were",
        "will",
        "would",
        "could",
        "should",
        "about",
        "into",
        "over",
        "there",
        "their",
        "them",
        "they",
        "our",
        "any",
        "all",
        "get",
        "got",
        "its",
        "it's",
        "i'm",
        "don't",
        "doesn't",
        "please",
        "help",
        "need",
        "want",
        "know",
        "tell",
        "make",
        "use",
        "using",
        "que",
        "como",
        "cuando",
        "donde",
        "por",
        "para",
        "con",
        "una",
        "los",
        "las",
        "del",
        "puedo",
        "hay",
        "mis",
        "sus",
        "comment",
        "quoi",
        "quand",
        "pour",
        "avec",
        "une",
        "des",
        "les",
        "est",
        "pas",
        "mon",
        "vos",
        "wie",
        "was",
        "wann",
        "warum",
        "kann",
        "ich",
        "mit",
        "und",
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "nicht",
    ]
)


def terms(text: str) -> list[str]:
    return [w for w in (m.group(0).casefold() for m in WORD.finditer(text)) if w not in STOP]


@dataclass
class Topic:
    vector: dict[str, float]
    members: list[int] = field(default_factory=list)


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def cluster(
    questions: list[dict[str, Any]], *, threshold: float = 0.3, top: int = 20
) -> list[dict[str, Any]]:
    """``questions``: dicts with ``question`` and ``reason`` (and anything else, passed through
    as examples). Returns topics, largest first: label terms, count, reasons, examples."""
    docs = [Counter(terms(q["question"])) for q in questions]
    df: Counter[str] = Counter()
    for d in docs:
        df.update(d.keys())
    n = len(docs)
    vectors = [
        {t: (1 + math.log(c)) * math.log((1 + n) / (1 + df[t])) + 1e-9 for t, c in d.items()}
        for d in docs
    ]
    topics: list[Topic] = []
    for i, v in enumerate(vectors):
        if not v:
            continue
        best, score = None, 0.0
        for topic in topics:
            sim = _cosine(v, topic.vector)
            if sim > score:
                best, score = topic, sim
        if best is None or score < threshold:
            topics.append(Topic(dict(v), [i]))
            continue
        best.members.append(i)
        size = len(best.members)
        merged = {k: best.vector.get(k, 0.0) * (size - 1) / size for k in best.vector}
        for k, w in v.items():
            merged[k] = merged.get(k, 0.0) + w / size
        best.vector = merged
    out = []
    for topic in sorted(topics, key=lambda t: (-len(t.members), t.members[0])):
        label = [t for t, _ in sorted(topic.vector.items(), key=lambda kv: -kv[1])[:3]]
        members = [questions[i] for i in topic.members]
        central = max(topic.members, key=lambda i: _cosine(vectors[i], topic.vector))
        out.append(
            {
                "label": label,
                "count": len(members),
                "reasons": dict(Counter(str(m.get("reason")) for m in members)),
                "example": questions[central]["question"],
                "examples": [m["question"] for m in members[:5]],
                "conversations": [str(m.get("conversation_id")) for m in members[:20]],
            }
        )
    return out[:top]
