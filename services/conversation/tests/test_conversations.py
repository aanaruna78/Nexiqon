"""Conversations (CV-01): turns persist the answer contract; clarify, approval and handoff states;
ownership; feedback; retention."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from nexiqon_conversation.models import Conversation, Outbox
from nexiqon_conversation.retention import sweep
from nexiqon_core.db import TenantSessionFactory, create_engine

from .conftest import Stack, ok

pytestmark = pytest.mark.integration


def test_a_turn_persists_the_answer_contract(stack: Stack) -> None:
    c = stack.start()
    turn = stack.say(c["id"], "How do I invite a teammate?")
    reply = turn["reply"]
    assert reply["content"] == "Open Settings, then Members, and choose Invite [1]."
    contract = reply["contract"]
    assert (contract["status"], contract["intent"], contract["route"], contract["abstained"]) == (
        "completed",
        "product_question",
        "knowledge",
        False,
    )
    assert contract["citations"][0]["passage_id"] == stack.fakes.passages[0]["id"]
    assert reply["run_id"]
    detail = ok(stack.client.get(f"/v1/conversations/{c['id']}", headers=stack.headers()))
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["contract"]["citations"]
    assert detail["title"] == "How do I invite a teammate?"
    # Retention from the agent's profile (30 days), counted from the last activity.
    retain = datetime.fromisoformat(detail["retain_until"])
    assert timedelta(days=29) < retain - datetime.now(UTC) <= timedelta(days=30)


def test_history_is_passed_to_the_agent(stack: Stack) -> None:
    c = stack.start()
    stack.say(c["id"], "hi")
    stack.say(c["id"], "How do I invite a teammate?")
    answer = stack.fakes.chats("answer")[-1]
    assert [m["content"] for m in answer["messages"][1:3]] == ["hi", "Hello! How can I help?"]


def test_clarify_then_answer_in_the_same_conversation(stack: Stack) -> None:
    c = stack.start()
    first = stack.say(c["id"], "it is broken")
    assert first["conversation"]["status"] == "awaiting_input"
    assert first["reply"]["content"] == "Which part of the product do you mean?"
    assert first["reply"]["contract"]["kind"] == "clarify"
    second = stack.say(c["id"], "How do I invite a teammate?")
    assert second["conversation"]["status"] == "active"
    assert second["reply"]["contract"]["citations"]


def test_handoff_stores_a_summary_and_the_assistant_then_stays_quiet(stack: Stack) -> None:
    c = stack.start()
    turn = stack.say(c["id"], "I want to talk to someone")
    assert turn["conversation"]["status"] == "escalated"
    assert turn["conversation"]["handoff_summary"].startswith("Customer wants help")
    after = stack.say(c["id"], "hello? anyone?")
    assert after["reply"] is None
    assert after["user_message"]["content"] == "hello? anyone?"

    async def events() -> list[str]:
        engine = create_engine(stack.db_url)
        try:
            async with TenantSessionFactory(engine).system_session() as s:
                return list(await s.scalars(select(Outbox.type).where(Outbox.subject == c["id"])))
        finally:
            await engine.dispose()

    assert "nexiqon.conversation.escalated" in asyncio.run(events())


def test_end_users_see_only_their_own_conversations_staff_see_all(stack: Stack) -> None:
    mine = stack.start()
    other = stack.start(headers=stack.headers(actor="user-b"))
    assert [
        x["id"] for x in ok(stack.client.get("/v1/conversations", headers=stack.headers()))
    ] == [mine["id"]]
    assert (
        stack.client.get(f"/v1/conversations/{other['id']}", headers=stack.headers()).status_code
        == 404
    )
    stack.say(other["id"], "hijack", status=404)
    staff = stack.headers({"member"}, actor="agent-1")
    assert {x["id"] for x in ok(stack.client.get("/v1/conversations", headers=staff))} >= {
        mine["id"],
        other["id"],
    }
    stack.say(
        mine["id"], "staff typing", headers=staff, status=404
    )  # staff read; they do not speak as the user
    assert (
        stack.client.get(
            f"/v1/conversations/{mine['id']}", headers=stack.headers(tenant="b")
        ).status_code
        == 404
    )


def test_feedback_on_assistant_messages(stack: Stack) -> None:
    c = stack.start()
    reply = stack.say(c["id"], "How do I invite a teammate?")["reply"]
    assert (
        stack.client.post(
            f"/v1/messages/{reply['id']}/feedback",
            json={"rating": "down", "comment": "too short"},
            headers=stack.headers(),
        ).status_code
        == 204
    )
    user_msg = ok(stack.client.get(f"/v1/conversations/{c['id']}", headers=stack.headers()))[
        "messages"
    ][0]
    assert (
        stack.client.post(
            f"/v1/messages/{user_msg['id']}/feedback",
            json={"rating": "up"},
            headers=stack.headers(),
        ).status_code
        == 404
    )
    assert (
        stack.client.post(
            f"/v1/messages/{reply['id']}/feedback",
            json={"rating": "up"},
            headers=stack.headers(actor="user-b"),
        ).status_code
        == 404
    )


def test_agent_failures_become_a_polite_reply(stack: Stack) -> None:
    stack.fakes.passages = []  # not an error by itself...
    stack.fakes.answer = ""  # ...nor this; break the model instead:
    original = stack.fakes._chat

    def broken(body: dict) -> object:  # type: ignore[type-arg]
        import httpx

        return httpx.Response(502, json={"detail": "provider down"})

    stack.fakes._chat = broken  # type: ignore[assignment,method-assign]
    c = stack.start()
    turn = stack.say(c["id"], "Where is the billing portal hidden these days")
    assert turn["reply"]["contract"]["kind"] == "error"
    assert turn["reply"]["content"].startswith("Sorry, something went wrong")
    stack.fakes._chat = original  # type: ignore[method-assign]


def test_retention_sweep_deletes_only_expired_conversations(stack: Stack) -> None:
    keep, expire = stack.start(), stack.start()
    stack.say(expire["id"], "hi")

    async def run() -> int:
        engine = create_engine(stack.db_url)
        db = TenantSessionFactory(engine)
        try:
            async with db.session(stack.tenants.a.context) as s:
                await s.execute(
                    update(Conversation)
                    .where(Conversation.id == expire["id"])
                    .values(retain_until=datetime.now(UTC) - timedelta(days=1))
                )
            return await sweep(db)
        finally:
            await engine.dispose()

    assert asyncio.run(run()) >= 1
    assert (
        stack.client.get(f"/v1/conversations/{expire['id']}", headers=stack.headers()).status_code
        == 404
    )
    assert (
        stack.client.get(f"/v1/conversations/{keep['id']}", headers=stack.headers()).status_code
        == 200
    )
