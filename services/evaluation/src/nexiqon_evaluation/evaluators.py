"""Built-in evaluator plugins (QA-01). Deterministic: they need no model, so a run's score depends
only on what the assistant said. More evaluators (e.g. a model-graded one) are plugins in the
``nexiqon.evaluators`` entry-point group."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from nexiqon_sdk import EvalCase, EvalObservation, Manifest, PluginKind, Score

GROUP = "nexiqon.evaluators"


def normalise(text: str) -> str:
    """Case-, accent-width- and space-insensitive form for phrase matching."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", folded).strip()


def _manifest(name: str, title: str, description: str) -> Manifest:
    return Manifest(name=name, kind=PluginKind.EVALUATOR, title=title, description=description)


class SourceCited:
    manifest = _manifest(
        "source-cited",
        "Cites the right source",
        "The answer cites the document (and section) the question is about.",
    )

    def applies(self, case: EvalCase) -> bool:
        return bool(case.expected_source) and not case.must_abstain

    async def score(
        self, case: EvalCase, seen: EvalObservation, config: Mapping[str, Any]
    ) -> Score:
        source = normalise(case.expected_source or "")
        section = normalise(case.expected_section or "")
        for c in seen.citations:
            uri, label = normalise(c.source_uri or ""), normalise(c.citation)
            if (uri.endswith(source) or source in label) and (not section or section in label):
                return Score(1.0, True, f"Cited {c.citation}")
        cited = "; ".join(c.citation for c in seen.citations) or "nothing"
        return Score(0.0, False, f"Expected {case.expected_source}; cited {cited}")


class ContainsFacts:
    manifest = _manifest(
        "contains-facts",
        "States the expected facts",
        "The answer contains at least one of the expected phrases.",
    )

    def applies(self, case: EvalCase) -> bool:
        return bool(case.expected_phrases) and not case.must_abstain

    async def score(
        self, case: EvalCase, seen: EvalObservation, config: Mapping[str, Any]
    ) -> Score:
        answer = normalise(seen.answer)
        for phrase in case.expected_phrases:
            if normalise(phrase) in answer:
                return Score(1.0, True, f"Says “{phrase}”")
        return Score(0.0, False, "None of the expected phrases appear in the answer")


class HonestAbstention:
    manifest = _manifest(
        "abstention",
        "Knows when it does not know",
        "Answers questions its sources cover and says so when they do not.",
    )

    def applies(self, case: EvalCase) -> bool:
        return True

    async def score(
        self, case: EvalCase, seen: EvalObservation, config: Mapping[str, Any]
    ) -> Score:
        if seen.error:
            return Score(0.0, False, f"The run failed: {seen.error}")
        if case.must_abstain:
            return (
                Score(1.0, True, "Said it could not answer")
                if seen.abstained
                else Score(0.0, False, "Answered a question its sources do not cover")
            )
        return (
            Score(0.0, False, "Did not answer a question its sources cover")
            if seen.abstained
            else Score(1.0, True, "Answered")
        )


class Grounded:
    manifest = _manifest(
        "grounded",
        "Backs answers with sources",
        "Every answer that is given carries at least one verified citation.",
    )

    def applies(self, case: EvalCase) -> bool:
        return not case.must_abstain

    async def score(
        self, case: EvalCase, seen: EvalObservation, config: Mapping[str, Any]
    ) -> Score:
        if seen.abstained or seen.error:
            return Score(0.0, False, "No answer to check")
        if seen.citations:
            return Score(1.0, True, f"{len(seen.citations)} verified citation(s)")
        return Score(0.0, False, "Answered without a verified citation")


def builtin() -> list[Any]:
    return [SourceCited(), ContainsFacts(), HonestAbstention(), Grounded()]
