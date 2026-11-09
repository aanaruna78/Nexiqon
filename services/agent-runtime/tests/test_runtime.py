"""The SaaS Knowledge Assistant graph runs from configuration only (AG-01, AG-02)."""

from __future__ import annotations

import asyncio
import copy
import uuid
from typing import Any

import pytest

from nexiqon_agent_runtime.checkpointer import TenantCheckpointer
from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_core.tenancy import TenantContext

from .conftest import AGENT, PACK, Stack, build, ok

SEP = chr(0x203A)  # section separator used in citations

pytestmark = pytest.mark.integration


def tid() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def path(result: dict[str, Any]) -> list[str]:
    return [f"{s['node']}:{s.get('outcome')}" for s in result["steps"]]


def test_knowledge_question_is_answered_with_verified_citations(stack: Stack) -> None:
    r = stack.run(tid(), "How do I invite a teammate?")
    assert r["status"] == "completed"
    assert (r["intent"], r["route"]) == ("product_question", "knowledge")
    assert path(r) == ["route:knowledge", "retrieve:None", "validate:sufficient", "respond:done"]
    assert r["answer"]["citations"][0]["citation"] == "Admin Guide " + SEP + " Teammates"
    assert r["answer"]["abstained"] is False
    assert r["steps"][0]["method"] == "examples"  # an exact example needs no model call
    assert not stack.fakes.chats("classify")
    search = next(b for k, b in stack.fakes.calls if k == "search")
    assert search["collection_ids"] == [stack.fakes.collections["product-docs"]]
    answer_call = stack.fakes.chats("answer")[0]
    assert answer_call["messages"][0]["content"].startswith(
        "You are Acme Help, the support assistant for Acme."
    )
    assert answer_call["classification"] == "internal"
    trace = ok(stack.client.get(f"/v1/runs/{r['run_id']}", headers=stack.headers()))
    assert trace["status"] == "completed"
    assert trace["agent_versions"]["agent"] == 1
    assert len(trace["steps"]) == 4


def test_model_classifies_with_structured_output_and_answers_carry_the_strictest_label(
    stack: Stack,
) -> None:
    stack.fakes.intents = {"billing portal": "product_question"}
    stack.fakes.passages[0]["classification"] = "confidential"
    r = stack.run(tid(), "Where is the billing portal hidden these days")
    assert r["route"] == "knowledge"
    assert r["steps"][0]["method"] == "model"
    classify = stack.fakes.chats("classify")[0]
    assert classify["response_schema"]["properties"]["intent"]["enum"][-1] == "unclear"
    assert stack.fakes.chats("answer")[0]["classification"] == "confidential"


@pytest.mark.parametrize("profile", ["cloud-frontier", "on-prem-small"])
def test_runs_on_cloud_and_small_on_prem_profiles(stack: Stack, profile: str) -> None:
    stack.deploy("agent", f"support-{profile}", {**AGENT, "model_profile": profile})
    stack.fakes.intents = {"teammate": "product_question"}
    r = stack.run(tid(), "adding a teammate to my space", agent=f"support-{profile}")
    assert r["status"] == "completed"
    assert {c["profile"] for c in stack.fakes.chats()} == {profile}


def test_unclear_question_asks_once_then_resumes_without_repeating_the_question(
    stack: Stack,
) -> None:
    thread = tid()
    first = stack.run(thread, "it is broken")
    assert first["status"] == "interrupted"
    assert first["interrupt"] == {
        "kind": "clarify",
        "prompt": "Which part of the product do you mean?",
    }
    assert path(first) == ["route:unclear", "clarify:ask"]
    second = stack.run(thread, "How do I invite a teammate?")  # the reply resumes the same turn
    assert second["status"] == "completed"
    assert path(second)[-3:] == ["retrieve:None", "validate:sufficient", "respond:done"]
    assert len(stack.fakes.chats("clarify")) == 1  # resuming did not regenerate the question


def test_low_evidence_clarifies_then_escalates_with_a_summary(stack: Stack) -> None:
    stack.fakes.abstain = True
    thread = tid()
    first = stack.run(thread, "How do I invite a teammate?")
    assert path(first) == [
        "route:knowledge",
        "retrieve:None",
        "validate:insufficient",
        "clarify:ask",
    ]
    second = stack.run(thread, "How do I invite a teammate?")
    assert second["status"] == "completed"
    assert path(second)[-3:] == ["validate:insufficient", "clarify:unresolved", "escalate:done"]
    assert second["handoff"]["reason"] == "unresolved"
    assert second["handoff"]["summary"].startswith("Customer wants help")


def test_handoff_and_smalltalk(stack: Stack) -> None:
    r = stack.run(tid(), "I want to talk to someone")
    assert path(r) == ["route:handoff", "escalate:done"]
    assert r["handoff"]["reason"] == "user_request"
    hi = stack.run(tid(), "hi")
    assert path(hi) == ["route:smalltalk", "respond:done"]
    assert hi["answer"]["text"] == "Hello! How can I help?"


def test_tools_are_reported_unavailable_until_the_tool_gateway_exists(stack: Stack) -> None:
    r = stack.run(tid(), "What plan am I on?")
    assert path(r)[:3] == ["route:action_read", "lookup:None", "validate:insufficient"]
    assert r["steps"][1]["error"] == "tool_unavailable"


def test_write_actions_wait_for_approval(stack: Stack) -> None:
    import yaml

    pack = yaml.safe_load(PACK)
    pack["metadata"]["name"] = "approval-pack"
    pack["spec"]["tools"].append(
        {"name": "submit-request", "risk_level": "write", "confirmation": "always"}
    )
    pack["spec"]["intents"].append(
        {
            "name": "open_case",
            "route": "action",
            "tools": ["submit-request"],
            "examples": ["please open a case for me"],
        }
    )
    stack.deploy("domain_pack", "approval-pack", yaml.safe_dump(pack))
    stack.deploy("agent", "cases", {**AGENT, "pack": {"name": "approval-pack"}})
    thread = tid()
    first = stack.run(thread, "please open a case for me", agent="cases")
    assert first["status"] == "interrupted"
    assert first["interrupt"]["kind"] == "approval"
    assert "submit-request" in first["interrupt"]["prompt"]
    # A plain message cannot slip past a pending approval.
    stack.run(thread, "yes do it", agent="cases", status=409)
    declined = stack.run(thread, resume={"approved": False}, agent="cases")
    assert path(declined)[-2:] == ["confirm:declined", "respond:done"]
    assert declined["answer"]["kind"] == "declined"
    other = tid()
    stack.run(other, "please open a case for me", agent="cases")
    approved = stack.run(other, resume={"approved": True}, agent="cases")
    assert "lookup:None" in path(approved)


def test_threads_belong_to_their_actor_and_tenant(stack: Stack) -> None:
    thread = tid()
    first = stack.run(thread, "it is broken")
    other_user = stack.headers(actor="user-b")
    stack.run(thread, "hijack", headers=other_user, status=403)
    assert stack.client.get(f"/v1/runs/{first['run_id']}", headers=other_user).status_code == 404
    # Tenant B with the same thread id gets its own, empty thread (tenant-scoped ids).
    stack.deploy("domain_pack", "saas-knowledge-assistant", PACK, tenant="b")
    stack.deploy("agent", "support", AGENT, tenant="b")
    b = stack.run(thread, "How do I invite a teammate?", headers=stack.headers(tenant="b"))
    assert b["status"] == "completed"
    assert (
        stack.client.get(
            f"/v1/runs/{first['run_id']}", headers=stack.headers(tenant="b")
        ).status_code
        == 404
    )


def test_checkpoints_survive_a_restart_and_stay_in_their_tenant(
    stack: Stack, agent_db: Any
) -> None:
    thread = tid()
    stack.run(thread, "it is broken")
    # A brand-new app instance (as after a restart) resumes from the Postgres checkpoint.
    client, config, _ = build(agent_db, stack.tenants, stack.fakes)
    with client, config:
        r = ok(
            client.post(
                "/v1/agents/support/runs",
                json={"thread_id": thread, "input": "How do I invite a teammate?"},
                headers=stack.headers(),
            )
        )
    assert r["status"] == "completed"

    async def peek(tenant: uuid.UUID) -> Any:
        engine = create_engine(stack.db_url)
        try:
            saver = TenantCheckpointer(
                TenantSessionFactory(engine), TenantContext(tenant, "x", "service")
            )
            return await saver.aget_tuple({"configurable": {"thread_id": thread}})
        finally:
            await engine.dispose()

    assert asyncio.run(peek(stack.tenants.a.context.tenant_id)) is not None
    assert asyncio.run(peek(stack.tenants.b.context.tenant_id)) is None


def test_a_looping_graph_is_stopped(stack: Stack) -> None:
    import yaml

    pack = yaml.safe_load(PACK)
    loop = copy.deepcopy(pack["spec"]["graph"])
    loop["edges"] = [
        e for e in loop["edges"] if not (e["from"] == "validate" and e["when"] == "insufficient")
    ]
    loop["edges"].append({"from": "validate", "to": "retrieve", "when": "insufficient"})
    stack.deploy("agent", "loopy", {**AGENT, "graph_override": loop})
    stack.fakes.abstain = True
    r = stack.run(tid(), "How do I invite a teammate?", agent="loopy")
    assert r["status"] == "failed"
    assert "too many steps" in r["error"]


def test_graph_validation_endpoint(stack: Stack) -> None:
    import yaml

    graph = yaml.safe_load(PACK)["spec"]["graph"]
    assert (
        ok(stack.client.post("/v1/graphs/validate", json=graph, headers=stack.headers()))["valid"]
        is True
    )
    graph["entry"] = "missing"
    check = ok(stack.client.post("/v1/graphs/validate", json=graph, headers=stack.headers()))
    assert check["valid"] is False
    assert check["problems"]


def test_a_full_reply_to_a_clarifying_question_is_searched_on_its_own(stack: Stack) -> None:
    thread = tid()
    stack.run(thread, "it is broken")
    stack.run(thread, "How do I invite a teammate?")
    assert [b for k, b in stack.fakes.calls if k == "search"][-1][
        "query"
    ] == "How do I invite a teammate?"
    short = tid()
    stack.run(short, "it is broken")
    stack.fakes.intents = {"teammates": "product_question"}
    stack.run(short, "teammates")  # too short to stand alone: read with the original question
    assert [b for k, b in stack.fakes.calls if k == "search"][-1][
        "query"
    ] == "it is broken\nteammates"
