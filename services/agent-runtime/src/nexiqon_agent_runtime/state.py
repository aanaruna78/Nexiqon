"""Graph state (checkpointed per thread). Only plain JSON-able values: never tokens or clients."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    reply: str | None  # the user's answer to a clarifying question (routed on its own too)
    history: list[dict[str, str]]
    locale: str
    outcome: str | None
    intent: str | None
    route: str | None
    passages: list[dict[str, Any]]
    evidence: float
    abstain: bool
    tool: dict[str, Any] | None
    pending: dict[str, Any] | None  # what the user is being asked (clarify / approval)
    approval: dict[str, Any] | None  # a confirmed tool call: approval id, tool, exact arguments
    clarify_attempts: int
    declined: bool
    blocked: str | None  # a blocked topic the question touched (fixed refusal, AG-03)
    handoff_requested: bool  # the user pressed "talk to a person" (no intent guessing)
    failed_turns: int  # consecutive turns without a grounded answer; carries over (CV-02)
    answer: dict[str, Any] | None
    handoff: dict[str, Any] | None
    steps: list[dict[str, Any]]


def fresh_turn(
    question: str, history: list[dict[str, str]], locale: str, handoff: bool = False
) -> AgentState:
    """Every new user turn starts clean; only the history and the failed-turn count carry over."""
    return AgentState(
        question=question,
        reply=None,
        history=history,
        locale=locale,
        outcome=None,
        intent=None,
        route=None,
        passages=[],
        evidence=0.0,
        abstain=True,
        tool=None,
        pending=None,
        approval=None,
        clarify_attempts=0,
        declined=False,
        blocked=None,
        handoff_requested=handoff,
        answer=None,
        handoff=None,
        steps=[],
    )
