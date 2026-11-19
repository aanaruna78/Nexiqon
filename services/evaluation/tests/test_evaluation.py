"""Evaluation runs end to end (Temporal + Postgres), reports, the release gate as config uses it,
access rules and tenant isolation."""

from __future__ import annotations

from typing import Any

from .conftest import AGENT, Stack, ok, spec

QUESTIONS = [
    (
        "How long are invitations valid?",
        "getting-started.md",
        "Invite your team",
        "expire after 7 days",
    ),
    ("What is the API rate limit per minute?", "api.md", "Rate limits", "600 requests per minute"),
    ("How is data encrypted at rest?", "security.md", "Data encryption", "AES-256"),
]
UNANSWERABLE = "What is the CEO's home address?"


async def make_set(stack: Stack, name: str = "smoke") -> dict[str, Any]:
    cases = [
        {
            "question": q,
            "expected_source": doc,
            "expected_section": section,
            "expected_phrases": [phrase],
        }
        for q, doc, section, phrase in QUESTIONS
    ] + [{"question": UNANSWERABLE, "must_abstain": True}]
    result: dict[str, Any] = await stack.ok(
        "POST", "/v1/test-sets", 201, json={"name": name, "agent": AGENT, "cases": cases}
    )
    return result


def answer_well(stack: Stack, version: int, *, skip: int = 0) -> None:
    for q, doc, section, phrase in QUESTIONS[skip:]:
        stack.agents.grounded(version, q, f"They {phrase} [1].", doc, section)


async def test_a_pack_gold_set_becomes_a_test_set(stack: Stack) -> None:
    t = await stack.ok(
        "POST", "/v1/test-sets/from-pack", 201, json={"pack": "saas-knowledge-assistant"}
    )
    assert t["name"] == "saas-knowledge-assistant-gold"
    assert t["origin"] == "pack"
    cases = await stack.ok("GET", f"/v1/test-sets/{t['id']}/cases")
    assert len(cases) == t["case_count"] >= 30
    assert sum(c["must_abstain"] for c in cases) == 5
    first = cases[0]
    assert first["expected_source"]
    assert first["expected_section"]
    assert first["expected_phrases"]
    assert {c["lang"] for c in cases} >= {"en", "es", "ar"}
    await stack.ok(
        "POST", "/v1/test-sets/from-pack", 409, json={"pack": "saas-knowledge-assistant"}
    )
    await stack.ok("POST", "/v1/test-sets/from-pack", 404, json={"pack": "no-such-pack"})


async def test_a_run_asks_every_case_as_evaluation_and_scores_it(stack: Stack) -> None:
    v1 = await stack.draft(spec())
    t = await make_set(stack)
    answer_well(stack, v1, skip=1)  # the first question gets an "I don't know"
    run = await stack.run(v1, t["id"])
    assert run["status"] == "completed"
    assert run["current"]
    card = run["scorecard"]
    assert card["cases"] == 4
    assert card["passed"] == 3
    assert card["pass_rate"] == 0.75
    assert card["metrics"]["abstention"]["mean"] == 0.75
    assert card["tokens"] == 480
    assert card["by_lang"]["en"]["cases"] == 4
    # Each case was its own fresh turn, by evaluation's own identity, on the exact version.
    assert len(stack.agents.calls) == 4
    assert {c["ctx"].actor_id for c in stack.agents.calls} == {"service:evaluation"}
    assert {c["version"] for c in stack.agents.calls} == {v1}
    assert len({c["thread_id"] for c in stack.agents.calls}) == 4
    assert {c["path"] for c in stack.agents.calls} == {f"/v1/agents/{AGENT}/runs"}

    failed = await stack.ok("GET", f"/v1/runs/{run['id']}/results", params={"outcome": "failed"})
    assert [r["question"] for r in failed] == [QUESTIONS[0][0]]
    assert (
        failed[0]["scores"]["abstention"]["detail"] == "Did not answer a question its sources cover"
    )
    everything = await stack.ok("GET", f"/v1/runs/{run['id']}/results")
    assert len(everything) == 4
    assert everything[0]["passed"] is False

    report = await stack.ok("GET", "/v1/evaluations/reports", params={"agent": AGENT})
    assert [(r["version"], r["test_set"], r["scorecard"]["pass_rate"]) for r in report] == [
        (v1, "smoke", 0.75)
    ]


async def test_an_unavailable_assistant_fails_its_cases_without_stopping_the_run(
    stack: Stack,
) -> None:
    v1 = await stack.draft(spec())
    t = await make_set(stack)
    stack.agents.fail = True
    run = await stack.run(v1, t["id"])
    assert run["status"] == "completed"
    assert run["scorecard"]["errors"] == 4
    assert run["scorecard"]["pass_rate"] == 0.0


async def test_runs_need_a_real_version_and_cases(stack: Stack) -> None:
    v1 = await stack.draft(spec())
    t = await make_set(stack)
    empty = await stack.ok("POST", "/v1/test-sets", 201, json={"name": "empty"})
    await stack.ok(
        "POST", "/v1/runs", 400, json={"agent": AGENT, "version": v1, "test_set_id": empty["id"]}
    )
    await stack.ok(
        "POST", "/v1/runs", 404, json={"agent": AGENT, "version": 99, "test_set_id": t["id"]}
    )


async def test_answers_and_expected_facts_are_for_people_who_build_assistants(
    stack: Stack,
) -> None:
    v1 = await stack.draft(spec())
    t = await make_set(stack)
    answer_well(stack, v1)
    run = await stack.run(v1, t["id"])
    member = stack.headers("member")
    await stack.ok("GET", f"/v1/runs/{run['id']}", headers=member)  # scores: fine
    await stack.ok("GET", f"/v1/runs/{run['id']}/results", 403, headers=member)
    await stack.ok("GET", f"/v1/test-sets/{t['id']}/cases", 403, headers=member)
    editor = stack.headers("editor")
    await stack.ok("GET", f"/v1/runs/{run['id']}/results", headers=editor)


async def test_another_tenant_sees_nothing(stack: Stack) -> None:
    v1 = await stack.draft(spec())
    t = await make_set(stack)
    answer_well(stack, v1)
    run = await stack.run(v1, t["id"])
    other = stack.headers("owner", tenant="b", actor="user-b")
    assert await stack.ok("GET", "/v1/test-sets", headers=other) == []
    await stack.ok("GET", f"/v1/test-sets/{t['id']}", 404, headers=other)
    await stack.ok("GET", f"/v1/runs/{run['id']}", 404, headers=other)
    assert await stack.ok("GET", "/v1/runs", headers=other) == []
    tenant_a = stack.tenants.a.context.tenant_id
    report = await stack.app.state.lifecycle.delete_tenant(tenant_a)
    assert report.residue_check_passed
    assert report.deleted["results"] == 4
    assert await stack.ok("GET", "/v1/test-sets") == []


async def test_editing_cases_makes_earlier_runs_stale(stack: Stack) -> None:
    v1 = await stack.draft(spec())
    t = await make_set(stack)
    answer_well(stack, v1)
    run = await stack.run(v1, t["id"])
    cases = await stack.ok("GET", f"/v1/test-sets/{t['id']}/cases")
    await stack.ok("DELETE", f"/v1/test-sets/{t['id']}/cases/{cases[-1]['id']}", 204)
    assert not (await stack.ok("GET", f"/v1/runs/{run['id']}"))["current"]
    gate = await stack.ok(
        "POST", f"/v1/gates/agents/{AGENT}/check", json={"version": v1, "test_set": "smoke"}
    )
    assert not gate["passed"]
    assert gate["reasons"] == [{"code": "stale"}]


# ------------------------------------------------------------------ safe publish through config


async def publish(stack: Stack, version: int, status: int = 200, **body: Any) -> Any:
    r = await stack.config.post(
        f"/v1/objects/agent/{AGENT}/versions/{version}/publish",
        headers=body.pop("headers", stack.h),
        json=body or None,
    )
    return ok(r, status)


async def release(stack: Stack, version: int) -> None:
    await publish(stack, version)
    await stack.cfg("PUT", f"/v1/objects/agent/{AGENT}/deployments/dev", json={"version": version})


GATE = {"release_gate": {"enabled": True, "test_set": "smoke", "min_pass_rate": 0.75}}


async def test_without_a_release_gate_publishing_is_unchanged(stack: Stack) -> None:
    v1 = await stack.draft(spec())
    out = await publish(stack, v1)
    assert out["status"] == "published"
    assert out["gate"] is None
    assert stack.agents.calls == []


async def test_a_gated_version_needs_a_passing_evaluation_of_its_exact_content(
    stack: Stack,
) -> None:
    t = await make_set(stack)
    v1 = await stack.draft(spec(**GATE))
    blocked = await publish(stack, v1, 409)
    assert blocked["code"] == "release_gate_failed"
    assert blocked["errors"] == [{"code": "not_evaluated"}]

    answer_well(stack, v1)
    await stack.run(v1, t["id"])
    # The draft is edited after its evaluation: that evaluation no longer counts.
    await stack.draft(spec(**GATE, description="edited"))
    changed = await publish(stack, v1, 409)
    assert changed["errors"] == [{"code": "changed_since_evaluation"}]

    await stack.run(v1, t["id"])
    out = await publish(stack, v1)
    assert out["gate"]["passed"]
    assert out["gate"]["test_set"] == "smoke"
    assert out["gate"]["run_id"]


async def test_a_regression_against_the_live_version_blocks_publishing(stack: Stack) -> None:
    t = await make_set(stack)
    v1 = await stack.draft(spec(**GATE))
    answer_well(stack, v1)
    await stack.run(v1, t["id"])
    await release(stack, v1)

    v2 = await stack.draft(spec(**GATE, description="shorter prompt"))
    answer_well(stack, v2, skip=1)  # one answer got worse: 75%, the threshold, but < live 100%
    run = await stack.run(v2, t["id"])
    assert run["scorecard"]["pass_rate"] == 0.75
    blocked = await publish(stack, v2, 409)
    codes = {(r["code"], r.get("metric")) for r in blocked["errors"]}
    assert ("regression", "pass_rate") in codes

    # Editors cannot override; admins can, with a reason that is recorded.
    await publish(
        stack, v2, 403, headers=stack.headers("editor"), override_reason="Known gap, fix tomorrow"
    )
    await publish(stack, v2, 422, headers=stack.headers("admin"), override_reason="short")
    out = await publish(
        stack, v2, headers=stack.headers("admin"), override_reason="Known gap, fix tomorrow"
    )
    assert out["gate"]["overridden"]
    assert not out["gate"]["passed"]
    assert out["gate"]["baseline_version"] == v1


async def test_publishing_a_gated_version_fails_closed_without_evaluation(stack: Stack) -> None:
    v1 = await stack.draft(spec(**GATE))
    stack.app.state.db = None  # evaluation cannot answer
    blocked = await publish(stack, v1, 503)
    assert blocked["code"] == "service_unavailable"
    out = await publish(
        stack, v1, headers=stack.headers("admin"), override_reason="Evaluation is down for upgrade"
    )
    assert out["gate"]["reasons"] == [{"code": "evaluation_unavailable"}]
