"""Scoring for the model comparison (M-07); the live run needs real models."""

from __future__ import annotations

from tools.eval.model_bakeoff import ROOT, licence_for, load_cases, render, score, summarise

CASE = {
    "q": "How long are invitations valid?",
    "doc": "getting-started.md",
    "evidence": "expire after 7 days",
    "lang": "en",
}
PASSAGE = {
    "id": "p1",
    "text": "Invitations expire after 7 days.",
    "source_uri": "upload://getting-started.md",
}


def reply(answer: str, abstained: bool = False, cited: bool = True) -> dict:  # type: ignore[type-arg]
    return {
        "answer": answer,
        "abstained": abstained,
        "citations": [{"marker": "1", "passage_id": "p1"}] if cited else [],
        "search": {"passages": [PASSAGE]},
        "model": {"model": "qwen3-8b"},
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }


def test_scores_correct_cited_and_paraphrased_answers() -> None:
    exact = score(CASE, reply("Invitations expire after 7 days [1]."), 120)
    assert (exact.correct, exact.cited_right, exact.tokens) == (True, True, 320)
    paraphrase = score(CASE, reply("They last a week [1]."), 120)
    assert paraphrase.correct  # the cited passage carries the evidence
    uncited = score(CASE, reply("They last a week.", cited=False), 120)
    assert not uncited.correct


def test_abstaining_is_right_only_when_the_corpus_has_no_answer() -> None:
    negative = score(
        {"q": "CEO's address?", "lang": "en"}, reply("", abstained=True, cited=False), 50
    )
    missed = score(CASE, reply("", abstained=True, cited=False), 50)
    s = summarise(
        "on-prem-small", [negative, missed, score(CASE, reply("expire after 7 days [1]"), 80)]
    )
    assert s.abstained_correctly == 1.0
    assert s.correct == 0.5
    assert s.answered == 0.5
    assert s.model == "qwen3-8b"
    report = render([s], "saas-knowledge-assistant")
    assert "| on-prem-small | qwen3-8b | 50% |" in report
    assert "Apache-2.0" in report


def test_licences_and_gold_set() -> None:
    assert licence_for("qwen3-embedding-0.6b").startswith("Apache-2.0")
    assert licence_for("gpt-4.1").startswith("Proprietary")
    assert licence_for("mystery-7b").startswith("Unknown")
    cases = load_cases(ROOT / "packs/saas-knowledge-assistant/eval")
    assert any("evidence" not in c for c in cases)  # unanswerable questions included
    assert sum(1 for c in cases if "evidence" in c) >= 20
