"""Model comparison on a pack's gold set (M-07): answers, citations, abstention, speed, licences.

For each model profile, the pack's eval corpus is indexed into its own collection (embeddings
differ per profile), then every gold question is answered through ``/retrieval/v1/answer`` and
scored:

* **correct**: the answer is grounded and contains the gold evidence phrase (or cites a passage
  that does, when the model paraphrases);
* **cited right**: at least one citation points at the gold document;
* **abstained**: on questions the corpus cannot answer, the model said so instead of guessing;
* latency (p50/p95) and tokens per answer.

    uv run python -m tools.eval.model_bakeoff --tenant <slug> \\
        --profiles cloud-frontier,on-prem-small --out docs/qa/model-bakeoff.md
    # token: NEXIQON_TOKEN (IdP access token); default gateway http://localhost:8000

Choose defaults from the report, together with the licence column and data-location policy.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]

#: Licence of the model behind each provider/model name (checked when the defaults were chosen).
LICENCES: dict[str, str] = {
    "qwen3": "Apache-2.0 (open weights)",
    "qwen3.6": "Apache-2.0 (open weights)",
    "qwen3-embedding": "Apache-2.0 (open weights)",
    "qwen3-reranker": "Apache-2.0 (open weights)",
    "gpt": "Proprietary API (OpenAI terms; no training on API data)",
    "text-embedding-3": "Proprietary API (OpenAI terms; no training on API data)",
    "claude": "Proprietary API (Anthropic commercial terms; no training on API data)",
    "gemini": "Proprietary API (Google Cloud terms; no training on API data)",
    "extractive": "Built-in development stand-in (not a language model)",
}


def licence_for(model: str | None) -> str:
    name = (model or "").lower()
    for prefix in sorted(LICENCES, key=len, reverse=True):
        if name.startswith(prefix):
            return LICENCES[prefix]
    return "Unknown: check before use"


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


@dataclass
class Outcome:
    question: str
    lang: str
    answerable: bool
    abstained: bool
    correct: bool = False
    cited_right: bool = False
    latency_ms: float = 0.0
    tokens: int = 0
    model: str | None = None
    error: str | None = None


def score(case: dict[str, Any], reply: dict[str, Any], latency_ms: float) -> Outcome:
    """Score one answer against its gold case (``doc``/``evidence`` absent: unanswerable)."""
    answerable = "evidence" in case
    passages = {p["id"]: p for p in (reply.get("search") or {}).get("passages", [])}
    cited = [
        passages[c["passage_id"]] for c in reply.get("citations", []) if c["passage_id"] in passages
    ]
    usage = reply.get("usage") or {}
    out = Outcome(
        question=case["q"],
        lang=case.get("lang", "en"),
        answerable=answerable,
        abstained=bool(reply.get("abstained")),
        latency_ms=latency_ms,
        tokens=int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
        model=(reply.get("model") or {}).get("model"),
    )
    if answerable and not out.abstained:
        phrase = _norm(case["evidence"])
        out.correct = phrase in _norm(reply.get("answer") or "") or any(
            phrase in _norm(p.get("text", "")) for p in cited
        )
        out.cited_right = any(str(p.get("source_uri", "")).endswith(case["doc"]) for p in cited)
    return out


@dataclass
class Summary:
    profile: str
    model: str | None
    answerable: int
    correct: float
    cited_right: float
    answered: float
    abstained_correctly: float
    p50_ms: float
    p95_ms: float
    tokens_per_answer: float
    errors: int
    by_language: dict[str, float] = field(default_factory=dict)
    misses: list[str] = field(default_factory=list)


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summarise(profile: str, outcomes: list[Outcome]) -> Summary:
    ok = [o for o in outcomes if o.error is None]
    answerable = [o for o in ok if o.answerable]
    negative = [o for o in ok if not o.answerable]
    langs = sorted({o.lang for o in answerable})

    def share(items: list[Outcome], test: Any) -> float:
        return round(sum(1 for o in items if test(o)) / len(items), 3) if items else 0.0

    return Summary(
        profile=profile,
        model=next((o.model for o in ok if o.model), None),
        answerable=len(answerable),
        correct=share(answerable, lambda o: o.correct),
        cited_right=share(answerable, lambda o: o.cited_right),
        answered=share(answerable, lambda o: not o.abstained),
        abstained_correctly=share(negative, lambda o: o.abstained),
        p50_ms=round(_pct([o.latency_ms for o in ok], 0.5)),
        p95_ms=round(_pct([o.latency_ms for o in ok], 0.95)),
        tokens_per_answer=round(statistics.fmean([o.tokens for o in ok]), 1) if ok else 0.0,
        errors=len(outcomes) - len(ok),
        by_language={
            lang: share([o for o in answerable if o.lang == lang], lambda o: o.correct)
            for lang in langs
        },
        misses=[o.question for o in answerable if not o.correct][:10],
    )


def render(summaries: list[Summary], pack: str) -> str:
    lines = [
        f"# Model comparison: {pack}",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} by `tools/eval/model_bakeoff.py`.",
        "",
        "| Profile | Model | Correct | Cited right | Answered | Abstained when it should | p50 | p95 | Tokens/answer | Licence |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(
            f"| {s.profile} | {s.model or '—'} | {s.correct:.0%} | {s.cited_right:.0%} | {s.answered:.0%} "
            f"| {s.abstained_correctly:.0%} | {s.p50_ms:.0f} ms | {s.p95_ms:.0f} ms | {s.tokens_per_answer:.0f} "
            f"| {licence_for(s.model)} |"
        )
    for s in summaries:
        lines += ["", f"## {s.profile}", ""]
        lines.append("By language: " + ", ".join(f"{k} {v:.0%}" for k, v in s.by_language.items()))
        if s.errors:
            lines.append(f"\n{s.errors} questions failed with errors.")
        if s.misses:
            lines += ["", "Not answered correctly:", *[f"- {q}" for q in s.misses]]
    return "\n".join(lines) + "\n"


def load_cases(pack: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load((pack / "gold.yaml").read_text(encoding="utf-8"))
    return [*raw["cases"], *(raw.get("unanswerable") or [])]


def _index(gw: httpx.Client, pack: Path, name: str, model: str, retrieval: str) -> str:
    collections = gw.get("/ingestion/v1/collections").json()
    existing = next((c for c in collections if c["name"] == name), None)
    if existing:
        return str(existing["id"])
    c = gw.post(
        "/ingestion/v1/collections",
        json={"name": name, "model_profile": model, "retrieval_profile": retrieval},
    )
    c.raise_for_status()
    pending = []
    for path in sorted((pack / "corpus").glob("*")):
        r = gw.post(
            f"/ingestion/v1/collections/{c.json()['id']}/documents",
            params={"filename": path.name},
            content=path.read_bytes(),
            headers={"content-type": "text/markdown"},
        )
        r.raise_for_status()
        pending.append(r.json()["document"]["id"])
    for doc in pending:
        for _ in range(900):
            if gw.get(f"/ingestion/v1/documents/{doc}").json()["status"] in (
                "ready",
                "failed",
                "quarantined",
            ):
                break
            time.sleep(1)
    return str(c.json()["id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--gateway", default="http://localhost:8000")
    parser.add_argument("--tenant", required=True, help="workspace slug")
    parser.add_argument("--pack", default="saas-knowledge-assistant")
    parser.add_argument("--profiles", required=True, help="comma-separated model profiles")
    parser.add_argument("--retrieval-profile", default="standard")
    parser.add_argument("--out", type=Path, help="write the Markdown report here")
    args = parser.parse_args()
    token = os.environ.get("NEXIQON_TOKEN")
    if not token:
        sys.exit("Set NEXIQON_TOKEN to an access token for the workspace")
    gw = httpx.Client(
        base_url=args.gateway,
        headers={"Authorization": f"Bearer {token}", "X-Nexiqon-Tenant": args.tenant},
        timeout=180,
    )
    pack = ROOT / "packs" / args.pack / "eval"
    cases = load_cases(pack)
    summaries = []
    for profile in [p.strip() for p in args.profiles.split(",") if p.strip()]:
        collection = _index(gw, pack, f"bakeoff-{profile}", profile, args.retrieval_profile)
        outcomes = []
        for case in cases:
            started = time.perf_counter()
            r = gw.post(
                "/retrieval/v1/answer",
                json={
                    "query": case["q"],
                    "collection_ids": [collection],
                    "model_profile": profile,
                    "retrieval_profile": args.retrieval_profile,
                },
            )
            latency = (time.perf_counter() - started) * 1000
            if r.status_code >= 400:
                outcomes.append(
                    Outcome(
                        case["q"],
                        case.get("lang", "en"),
                        "evidence" in case,
                        False,
                        error=r.text[:200],
                    )
                )
                continue
            outcomes.append(score(case, r.json(), latency))
        summaries.append(summarise(profile, outcomes))
        print(f"{profile}: done", file=sys.stderr)
    report = render(summaries, args.pack)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
