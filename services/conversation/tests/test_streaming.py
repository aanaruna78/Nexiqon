"""Streamed turns through the conversation service (CH-01) and the handoff request (CV-02)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from .conftest import Stack, ok

pytestmark = pytest.mark.integration


def events(response: Any) -> list[tuple[str, dict[str, Any]]]:
    assert response.status_code == 200, response.text
    out = []
    for block in response.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def stream(
    stack: Stack, conversation: str, text: str, headers: dict[str, str] | None = None
) -> Any:
    return stack.client.post(
        f"/v1/conversations/{conversation}/messages/stream",
        json={"content": text},
        headers=headers or stack.headers(),
    )


def test_streamed_reply_is_relayed_and_stored(stack: Stack) -> None:
    c = stack.start()
    got = events(stream(stack, c["id"], "How do I invite a teammate?"))
    kinds = [k for k, _ in got]
    assert {"run", "status", "sources", "delta"} <= set(kinds)
    assert kinds[-1] == "message"
    assert "result" not in kinds  # the stored message replaces the agent's raw result
    text = "".join(d["text"] for k, d in got if k == "delta")
    turn = got[-1][1]
    assert turn["reply"]["content"] == text
    assert turn["reply"]["contract"]["citations"]
    assert turn["user_message"]["content"] == "How do I invite a teammate?"
    detail = ok(stack.client.get(f"/v1/conversations/{c['id']}", headers=stack.headers()))
    assert [m["content"] for m in detail["messages"]] == ["How do I invite a teammate?", text]


def test_stream_refusals_are_plain_http_errors(stack: Stack) -> None:
    c = stack.start()
    stranger = stack.headers(actor="user-b")
    assert stream(stack, c["id"], "hello", headers=stranger).status_code == 404


def test_handoff_button_escalates_with_a_summary(stack: Stack) -> None:
    c = stack.start()
    stack.say(c["id"], "it is broken")  # an open clarifying question does not block the button
    turn = ok(stack.client.post(f"/v1/conversations/{c['id']}/handoff", headers=stack.headers()))
    assert turn["user_message"]["content"] == "I'd like to talk to a person."
    assert turn["reply"]["contract"]["kind"] == "handoff"
    assert turn["conversation"]["status"] == "escalated"
    assert turn["conversation"]["handoff_summary"].startswith("Customer wants help")
    again = stack.client.post(f"/v1/conversations/{c['id']}/handoff", headers=stack.headers())
    assert again.status_code == 409
    quiet = events(stream(stack, c["id"], "hello?"))
    assert [k for k, _ in quiet] == ["message"]
    assert quiet[0][1]["reply"] is None  # a person has it now: the assistant stays quiet


def test_keys_limited_to_assistants_see_only_their_conversations(stack: Stack) -> None:
    """QA3-02: a member key limited to another assistant cannot read or list these."""
    from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext

    c = stack.start(headers=stack.headers(actor="someone"))
    stack.say(c["id"], "How do I invite a teammate?", headers=stack.headers(actor="someone"))
    t = stack.tenants.a.context.tenant_id

    def key(agents: set[str]) -> dict[str, str]:
        ctx = TenantContext(t, "key:k", "api_key", frozenset({"member"}), agents=frozenset(agents))
        return {CONTEXT_HEADER: stack.tenants.issuer.issue(ctx)}

    billing = key({"billing"})
    assert stack.client.get(f"/v1/conversations/{c['id']}", headers=billing).status_code == 404
    assert ok(stack.client.get("/v1/conversations", headers=billing)) == []
    support = key({"support"})
    assert ok(stack.client.get(f"/v1/conversations/{c['id']}", headers=support))["messages"]
    assert [x["id"] for x in ok(stack.client.get("/v1/conversations", headers=support))] == [
        c["id"]
    ]


def test_restricted_answers_keep_later_calls_restricted(stack: Stack) -> None:
    """QA3-04: history carries the strictest label of what the assistant already said."""
    stack.fakes.passages[0]["classification"] = "restricted"
    stack.fakes.answer = "Open Settings, then Members, and choose Invite [1]."
    c = stack.start()
    first = stack.say(c["id"], "How do I invite a teammate?")
    assert first["reply"]["contract"]["classification"] == "restricted"
    stack.say(c["id"], "hi")
    smalltalk = stack.fakes.chats("smalltalk")[-1]
    assert any("choose Invite" in str(m.get("content")) for m in smalltalk["messages"])
    assert smalltalk["classification"] == "restricted"
