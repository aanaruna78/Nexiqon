"""ST-16 and MT-02 inputs: the escalation queue, staff replies, and the content-gap feed."""

from __future__ import annotations

from .conftest import Stack, ok

STAFF = {"member"}


def queue(stack: Stack, cid: str, action: str, status: int = 200, actor: str = "agent-1") -> object:
    return ok(
        stack.client.post(
            f"/v1/conversations/{cid}/queue",
            json={"action": action},
            headers=stack.headers(STAFF, actor=actor),
        ),
        status,
    )


def test_handed_over_conversations_wait_in_the_queue_until_resolved(stack: Stack) -> None:
    c = stack.start()
    stack.say(c["id"], "I want to talk to someone")
    staff = stack.headers(STAFF, actor="agent-1")
    waiting = ok(stack.client.get("/v1/conversations", params={"queue": "waiting"}, headers=staff))
    assert [x["id"] for x in waiting] == [c["id"]]
    assert waiting[0]["queue_status"] == "open"
    claimed = queue(stack, c["id"], "claim")
    assert (claimed["queue_status"], claimed["assignee"]) == ("claimed", "agent-1")  # type: ignore[index]
    assert queue(stack, c["id"], "claim", 409, actor="agent-2")["code"] == "conflict"  # type: ignore[index]

    reply = ok(
        stack.client.post(
            f"/v1/conversations/{c['id']}/staff-messages",
            json={"content": "Hi, I'm Sam from support. Looking at your account now."},
            headers=staff,
        ),
        201,
    )
    assert reply["role"] == "staff"
    assert reply["contract"] == {"kind": "human", "author": "agent-1"}
    # The visitor sees it in their conversation; the assistant stays quiet.
    detail = ok(stack.client.get(f"/v1/conversations/{c['id']}", headers=stack.headers()))
    assert detail["messages"][-1]["content"].startswith("Hi, I'm Sam")

    queue(stack, c["id"], "resolve")
    assert (
        ok(stack.client.get("/v1/conversations", params={"queue": "waiting"}, headers=staff)) == []
    )
    done = ok(stack.client.get("/v1/conversations", params={"queue": "resolved"}, headers=staff))
    assert done[0]["resolved_at"]


def test_visitors_cannot_work_the_queue_and_only_handovers_take_staff_replies(stack: Stack) -> None:
    c = stack.start()
    stack.say(c["id"], "How do I invite a teammate?")
    r = stack.client.post(
        f"/v1/conversations/{c['id']}/queue", json={"action": "claim"}, headers=stack.headers()
    )
    assert r.status_code == 403
    queue(stack, c["id"], "claim", 409)  # never handed over
    r = stack.client.post(
        f"/v1/conversations/{c['id']}/staff-messages",
        json={"content": "hello"},
        headers=stack.headers(STAFF),
    )
    assert r.status_code == 409


def test_gap_questions_are_the_ones_the_assistant_could_not_handle(stack: Stack) -> None:
    answered = stack.start()
    stack.say(answered["id"], "How do I invite a teammate?")
    stack.fakes.abstain = True
    unknown = stack.start()
    # Too little evidence: the assistant asks the person to rephrase instead of answering.
    stack.say(unknown["id"], "How do I invite a teammate?")
    stack.fakes.abstain = False
    rated = stack.start()
    turn = stack.say(rated["id"], "How do I invite a teammate to two workspaces?")
    ok(
        stack.client.post(
            f"/v1/messages/{turn['reply']['id']}/feedback",
            json={"rating": "down"},
            headers=stack.headers(),
        ),
        204,
    )
    handed = stack.start()
    stack.say(handed["id"], "I want to talk to someone")
    gaps = ok(stack.client.get("/v1/insights/gap-questions", headers=stack.headers(STAFF)))
    found = {(g["question"], g["reason"]) for g in gaps}
    assert found == {
        ("How do I invite a teammate?", "unanswered"),
        ("How do I invite a teammate to two workspaces?", "not_helpful"),
        ("I want to talk to someone", "escalated"),
    }
    r = stack.client.get("/v1/insights/gap-questions", headers=stack.headers())
    assert r.status_code == 403  # visitors never see other people's questions
