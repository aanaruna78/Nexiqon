"""Evaluator plugins, scorecards and the release-gate rules (no database)."""

from __future__ import annotations

from nexiqon_evaluation.evaluators import ContainsFacts, Grounded, HonestAbstention, SourceCited
from nexiqon_evaluation.main import evaluator_registry
from nexiqon_evaluation.runner import score_case
from nexiqon_evaluation.scoring import CaseOutcome, Thresholds, gate, scorecard
from nexiqon_sdk import EvalCase, EvalCitation, EvalObservation, PluginKind

CASE = EvalCase(
    question="How long are invitations valid?",
    expected_source="getting-started.md",
    expected_section="Invite your team",
    expected_phrases=("expire after 7 days",),
)
GOOD = EvalObservation(
    answer="Invitations  EXPIRE after 7 days [1].",
    abstained=False,
    citations=(
        EvalCitation("Getting Started \u203a Invite your team", "upload://getting-started.md"),
    ),
)


async def test_each_evaluator_explains_its_score() -> None:
    assert (await SourceCited().score(CASE, GOOD, {})).passed
    wrong = EvalObservation(
        answer="x",
        abstained=False,
        citations=(EvalCitation("Billing \u203a Plans", "upload://billing.md"),),
    )
    miss = await SourceCited().score(CASE, wrong, {})
    assert not miss.passed
    assert "Billing \u203a Plans" in miss.detail
    assert (await ContainsFacts().score(CASE, GOOD, {})).passed  # case and spaces do not matter
    assert not (await ContainsFacts().score(CASE, wrong, {})).passed
    assert (await Grounded().score(CASE, GOOD, {})).passed
    assert not (await Grounded().score(CASE, EvalObservation("yes", False), {})).passed


async def test_abstaining_is_right_only_when_the_sources_do_not_answer() -> None:
    unanswerable = EvalCase(question="What is the CEO's home address?", must_abstain=True)
    said_no = EvalObservation("I could not find that.", abstained=True)
    assert (await HonestAbstention().score(unanswerable, said_no, {})).passed
    assert not (await HonestAbstention().score(unanswerable, GOOD, {})).passed
    assert not (await HonestAbstention().score(CASE, said_no, {})).passed
    failed = EvalObservation("", abstained=True, error="503")
    assert not (await HonestAbstention().score(unanswerable, failed, {})).passed
    # Fact and source evaluators have nothing to say about a question with no answer.
    assert not SourceCited().applies(unanswerable)
    assert not ContainsFacts().applies(unanswerable)


async def test_a_case_passes_only_when_every_applicable_evaluator_does() -> None:
    registry = evaluator_registry()
    assert {m.name for m in registry.manifests(PluginKind.EVALUATOR)} == {
        "abstention",
        "contains-facts",
        "grounded",
        "source-cited",
    }
    scores, passed = await score_case(registry, [], CASE, GOOD)
    assert passed
    assert set(scores) == {"abstention", "contains-facts", "grounded", "source-cited"}
    no_fact = EvalObservation("Soon [1].", False, GOOD.citations)
    scores, passed = await score_case(registry, [], CASE, no_fact)
    assert not passed
    assert not scores["contains-facts"]["passed"]
    # A test set may choose its evaluators.
    scores, passed = await score_case(registry, ["source-cited"], CASE, no_fact)
    assert passed
    assert set(scores) == {"source-cited"}


def test_scorecard_totals_metrics_languages_and_latency() -> None:
    ok = {"abstention": {"value": 1.0, "passed": True}}
    bad = {"abstention": {"value": 0.0, "passed": False}}
    card = scorecard(
        [
            CaseOutcome("en", True, ok, latency_ms=100, tokens=10, cost=0.01),
            CaseOutcome("en", False, bad, latency_ms=300, tokens=10, cost=0.01),
            CaseOutcome("ar", True, ok, latency_ms=200, tokens=10, cost=0.01),
            CaseOutcome("ar", False, {}, error=True),
        ]
    )
    assert card["cases"] == 4
    assert card["passed"] == 2
    assert card["errors"] == 1
    assert card["pass_rate"] == 0.5
    assert card["metrics"]["abstention"] == {"mean": 0.6667, "cases": 3}
    assert card["by_lang"] == {
        "ar": {"cases": 2, "pass_rate": 0.5},
        "en": {"cases": 2, "pass_rate": 0.5},
    }
    assert card["latency_ms"] == {"p50": 200, "p95": 300}
    assert card["tokens"] == 30
    assert card["cost"] == 0.03


def test_gate_rules() -> None:
    limits = Thresholds(min_pass_rate=0.8, max_drop=0.05)
    good = {"pass_rate": 0.9, "metrics": {"grounded": {"mean": 0.9}}}
    assert gate(None, None, limits).reasons == [{"code": "not_evaluated"}]
    assert gate(good, None, limits, stale=True).reasons == [{"code": "stale"}]
    assert gate(good, None, limits).passed
    low = gate({"pass_rate": 0.7, "metrics": {}}, None, limits)
    assert not low.passed
    assert low.reasons[0]["code"] == "below_threshold"
    # Better than the threshold but worse than what is live: a regression blocks it.
    live = {"pass_rate": 1.0, "metrics": {"grounded": {"mean": 1.0}}}
    worse = gate(good, live, limits)
    assert not worse.passed
    assert {r["metric"] for r in worse.reasons} == {"pass_rate", "grounded"}
    assert worse.deltas == {"pass_rate": -0.1, "grounded": -0.1}
    # A drop within the allowance passes.
    near = gate({"pass_rate": 0.96, "metrics": {}}, {"pass_rate": 1.0, "metrics": {}}, limits)
    assert near.passed
    assert near.deltas == {"pass_rate": -0.04}
