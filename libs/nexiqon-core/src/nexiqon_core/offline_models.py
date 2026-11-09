"""Deterministic offline "models" for development stacks, tests and evaluations without a model.

* ``hash_embed``: 1024-d character n-gram hashing vectors (similar wording -> similar vectors);
* ``lexical_scores``: query-term overlap, a stand-in reranker;
* ``extractive_answer``: picks the passage sentence that best matches the question and cites it.

None of these understand language. They let every pipeline stage run end to end; real quality
comes from real models (model bake-off, M-07). The model gateway serves them only when an operator
enables the ``offline`` provider (development).
"""

from __future__ import annotations

import hashlib
import math
import re

DIMS = 1024
EMBED_MODEL = "hash-ngram-1024"
WORD = re.compile(r"\w+", re.UNICODE)
SENTENCE = re.compile("(?<=[.!?" + "".join(map(chr, (0x3002, 0xFF01, 0xFF1F, 0x061F))) + r"])\s+")
PASSAGE = re.compile(r"^\[(\w{1,8})\][^\n]*\n(.*?)(?=^\[\w{1,8}\]|\Z)", re.MULTILINE | re.DOTALL)
STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "de",
        "do",
        "does",
        "el",
        "en",
        "es",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "la",
        "las",
        "los",
        "of",
        "on",
        "or",
        "que",
        "the",
        "this",
        "to",
        "un",
        "una",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "y",
    ]
)


def _terms(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if len(w) > 1 and w not in STOP}


def hash_embed(text: str) -> list[float]:
    vec = [0.0] * DIMS
    for word in WORD.findall(text.lower()):
        padded = f"#{word}#"
        grams = [padded[i : i + 3] for i in range(max(1, len(padded) - 2))] + [f"w:{word}"]
        for gram in grams:
            h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "big")
            vec[h % DIMS] += 1.0 if (h >> 63) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def lexical_scores(query: str, documents: list[str]) -> list[float]:
    q = _terms(query)
    return [len(q & _terms(d)) / (len(q) or 1) for d in documents]


def extractive_answer(prompt: str, question: str) -> str:
    """From a prompt holding ``[n] label`` blocks, return the best-matching sentence with ``[n]``."""
    q = _terms(question)
    sources = prompt.split("\nQuestion:", 1)[0]  # never "answer" with the question itself
    best: tuple[float, str, str] = (0.0, "", "")
    for marker, body in PASSAGE.findall(sources):
        for sentence in SENTENCE.split(" ".join(body.split())):
            words = _terms(sentence)
            score = len(q & words) / (len(q) or 1)
            if score > best[0]:
                best = (score, marker, sentence.strip())
    if not best[1]:
        return "I could not find this in the provided sources."
    return f"{best[2]} [{best[1]}]"
