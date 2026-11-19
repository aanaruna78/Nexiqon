"""W-03: a visitor emails themselves a copy of their own conversation, and nothing more."""

from __future__ import annotations

from .conftest import Stack, ok

EMAIL = "visitor@example.com"


def send(stack: Stack, conversation: str, status: int = 202, **kw: object) -> object:
    return ok(
        stack.client.post(
            f"/v1/conversations/{conversation}/transcript",
            json={"email": kw.pop("email", EMAIL)},
            headers=kw.pop("headers", stack.headers()),  # type: ignore[arg-type]
        ),
        status,
    )


def test_a_visitor_gets_a_copy_of_what_they_saw(stack: Stack) -> None:
    c = stack.start()
    stack.say(c["id"], "How do I invite a teammate?")
    out = send(stack, c["id"])
    assert out["sent"] is True  # type: ignore[index]
    [mail] = stack.mail.sent
    assert mail.to == EMAIL
    assert mail.subject == "Your conversation with Support"
    assert "How do I invite a teammate?" in mail.text
    assert "Open Settings, then Members, and choose Invite [1]." in mail.text
    assert "Sources:" in mail.text
    # Nothing from behind the answer.
    assert "run_id" not in mail.text
    assert "passage" not in mail.text
    # One copy per conversation every few minutes.
    assert send(stack, c["id"], 429)["code"] == "transcript_too_soon"  # type: ignore[index]


def test_only_the_person_in_the_conversation_can_ask_for_it(stack: Stack) -> None:
    c = stack.start()
    stack.say(c["id"], "How do I invite a teammate?")
    other = stack.headers(actor="someone-else")
    send(stack, c["id"], 404, headers=other)
    staff = stack.headers({"member"}, actor="agent-1")
    send(stack, c["id"], 404, headers=staff)  # staff read it in Studio; they do not mail it
    assert stack.mail.sent == []


def test_bad_addresses_empty_conversations_and_one_inbox_flooded(stack: Stack) -> None:
    empty = stack.start()
    send(stack, empty["id"], 400)
    c = stack.start()
    stack.say(c["id"], "How do I invite a teammate?")
    assert send(stack, c["id"], 400, email="not an address <x@y>")["code"] == "bad_request"  # type: ignore[index]
    # A second visitor cannot send unlimited copies to one inbox, conversation after conversation.
    for i in range(3):
        v = stack.headers(actor=f"visitor-{i}")
        conv = stack.start(headers=v)
        stack.say(conv["id"], "How do I invite a teammate?", headers=v)
        send(stack, conv["id"], headers=v, email="target@example.com")
    v = stack.headers(actor="visitor-9")
    conv = stack.start(headers=v)
    stack.say(conv["id"], "How do I invite a teammate?", headers=v)
    send(stack, conv["id"], 429, headers=v, email="TARGET@example.com")
    assert len(stack.mail.sent) == 3
