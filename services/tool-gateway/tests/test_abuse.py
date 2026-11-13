"""Tool authorisation and abuse suite (T-05): zero unauthorised calls leave the gateway.

Seeded random fuzzing over callers, agents, tools, arguments and confirmations. For every attempt
the expected verdict is computed independently from the rules; the test fails if any request
reached the upstream when it should not have, or went anywhere but the allowlisted, pinned host.
"""

from __future__ import annotations

import random
import uuid
from typing import Any

import pytest

from .conftest import API, API_IP, Stack, ok

pytestmark = pytest.mark.integration

NASTY = [
    "",
    "a",
    "../../etc/passwd",
    "http://169.254.169.254/",
    "x?admin=1",
    "@evil.example",
    "%00",
    "‮",
    "a/b/c",
    "' OR 1=1 --",
    "{{caller.actor_id}}",
    "${jndi:ldap://x}",
    "A" * 300,
    "<script>",
    "\\\\server\\share",
]
ROLES = [{"end_user"}, {"member"}, {"viewer"}, {"editor"}, {"admin"}, set()]


def _arguments(rng: random.Random) -> dict[str, Any]:
    pick = rng.random()
    if pick < 0.25:
        return {}
    if pick < 0.5:
        return {"case_id": rng.choice(NASTY)}
    if pick < 0.75:
        return {"subject": rng.choice(NASTY), "description": rng.choice(NASTY)}
    return {
        rng.choice(["subject", "case_id", "x", "customer_id", "__proto__"]): rng.choice(
            [rng.choice(NASTY), 1, None, [], {"a": 1}]
        )
    }


def test_fuzzed_calls_never_escape_the_rules(stack: Stack) -> None:
    rng = random.Random(20261113)  # noqa: S311 - reproducible fuzzing, not security
    stack.deploy(
        "agent",
        "no-tools",
        {"pack": {"name": "saas-knowledge-assistant"}, "display_name": "Nothing", "tools": []},
    )
    unexpected: list[str] = []
    for i in range(150):
        roles = rng.choice(ROLES)
        actor_type = rng.choice(["user", "user", "widget"])
        tool = rng.choice(["account-lookup", "open-case", "case-status", "ghost"])
        agent = rng.choice(["support", "support", "no-tools"])
        arguments = _arguments(rng)
        approval = str(uuid.uuid4()) if rng.random() < 0.3 else None
        before = len(stack.upstream.requests)
        body: dict[str, Any] = {
            "agent": agent,
            "arguments": arguments,
            "idempotency_key": f"fuzz-{i}",
        }
        if approval:
            body["approval_id"] = approval
        r = stack.client.post(
            f"/v1/tools/{tool}/invoke",
            json=body,
            headers=stack.headers(roles, actor=f"u{i}", actor_type=actor_type),
        )
        sent = stack.upstream.requests[before:]
        # Mirrors the policy: a role must grant tool.invoke.<risk>; widgets are limited to an action
        # list that includes read/write tool calls (identity only ever gives widget keys end_user).
        may_invoke = bool(roles & {"end_user", "member", "editor", "admin"})
        allowed = tool != "ghost" and agent == "support" and may_invoke
        valid = (tool == "account-lookup" and arguments == {}) or (
            tool == "case-status"
            and set(arguments) == {"case_id"}
            and isinstance(arguments["case_id"], str)
            and len(arguments["case_id"]) <= 200
        )
        # open-case is a write: no forged confirmation can ever be enough.
        should_call = allowed and valid and tool != "open-case"
        if sent and not should_call:
            unexpected.append(
                f"#{i} {tool} {agent} {roles} {actor_type} {arguments!r} -> {r.status_code}"
            )
        for request in sent:
            if (
                request.url.host != API_IP
                or request.headers["host"] != API
                or request.url.raw_path.decode().count("/") > 2
            ):
                unexpected.append(f"#{i} escaped to {request.url!r}")
    assert unexpected == []
    assert len(stack.upstream.requests) >= 5  # the fuzz also exercised real, allowed calls


def test_cross_tenant_confirmations_and_replays(stack: Stack) -> None:
    args = {"subject": "Cannot log in"}
    pending = ok(
        stack.client.post(
            "/v1/tools/open-case/approvals",
            json={"agent": "support", "arguments": args},
            headers=stack.headers(),
        ),
        201,
    )
    ok(
        stack.client.post(
            f"/v1/approvals/{pending['id']}/decision",
            json={"approved": True},
            headers=stack.headers(),
        )
    )
    before = len(stack.upstream.requests)
    # Same actor id in another tenant: the confirmation does not exist there.
    b = stack.headers(tenant="b")
    assert stack.client.post(
        "/v1/tools/open-case/invoke",
        json={
            "agent": "support",
            "arguments": args,
            "idempotency_key": "x",
            "approval_id": pending["id"],
        },
        headers=b,
    ).status_code in (403, 404)
    assert (
        stack.client.post(
            f"/v1/approvals/{pending['id']}/decision", json={"approved": True}, headers=b
        ).status_code
        == 404
    )
    assert len(stack.upstream.requests) == before
    # A confirmation for one tool cannot run another.
    stack.deploy("tool", "open-case-2", {**_case_spec(stack)})
    stack.deploy(
        "agent",
        "two",
        {
            "pack": {"name": "saas-knowledge-assistant"},
            "display_name": "Two tools",
            "tools": ["open-case", "open-case-2"],
        },
    )
    r = stack.client.post(
        "/v1/tools/open-case-2/invoke",
        json={
            "agent": "two",
            "arguments": args,
            "idempotency_key": "y",
            "approval_id": pending["id"],
        },
        headers=stack.headers(),
    )
    assert r.status_code == 403
    assert len(stack.upstream.requests) == before


def _case_spec(stack: Stack) -> dict[str, Any]:
    from .conftest import CASE_TOOL

    return dict(CASE_TOOL)
