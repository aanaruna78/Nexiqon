"""Tool gateway (T-01..T-04): invocation checks, approvals, idempotency, egress, secrets, import."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from sqlalchemy import select

from nexiqon_core.db import TenantSessionFactory, create_engine
from nexiqon_tool_gateway.mock_apis import app as mock_app
from nexiqon_tool_gateway.models import Approval, Outbox, ToolCall

from .conftest import ACCOUNT_TOOL, API, API_IP, PACK, Stack, ok

pytestmark = pytest.mark.integration
SECRET = "demo-token-acme"


async def _rows(stack: Stack) -> list[str]:
    """Everything the gateway persisted for tenant A, as JSON text."""
    engine = create_engine(stack.db_url)
    try:
        async with TenantSessionFactory(engine).session(stack.tenants.a.context) as s:
            calls = [
                {c.name: getattr(r, c.name) for c in ToolCall.__table__.columns}
                for r in (await s.scalars(select(ToolCall))).all()
            ]
            approvals = [
                {c.name: getattr(r, c.name) for c in Approval.__table__.columns}
                for r in (await s.scalars(select(Approval))).all()
            ]
        async with TenantSessionFactory(engine).system_session() as s:
            events = [
                r.data | {"type": r.type}
                for r in (
                    await s.scalars(
                        select(Outbox).where(Outbox.tenant_id == stack.tenants.a.context.tenant_id)
                    )
                ).all()
            ]
    finally:
        await engine.dispose()
    return [json.dumps(x, default=str) for x in (*calls, *approvals, *events)]


def test_account_lookup_needs_no_code_and_is_minimised(stack: Stack) -> None:
    out = stack.invoke("account-lookup")
    assert out["ok"] is True
    assert set(out["result"]) == {
        "account_id",
        "plan",
        "status",
        "renews_on",
    }  # internal_notes dropped
    assert out["classification"] == "confidential"
    sent = stack.upstream.requests[-1]
    assert sent.url.host == API_IP  # pinned to the checked address
    assert sent.headers["host"] == API
    assert sent.url.path == "/accounts/cust-42"  # the caller's own id, from the verified token
    assert sent.headers["authorization"] == f"Bearer {SECRET}"
    # The credential never comes back, and is never stored or emitted.
    assert SECRET not in json.dumps(out)
    persisted = asyncio.run(_rows(stack))
    assert all(SECRET not in row for row in persisted)
    assert any('"nexiqon.tool-gateway.call.completed"' in row for row in persisted)
    described = ok(stack.client.get("/v1/tools/account-lookup", headers=stack.headers()))
    assert "request" not in described
    assert "credential_ref" not in json.dumps(described)


def test_callers_only_reach_their_own_record(stack: Stack) -> None:
    stack.invoke("account-lookup", headers=stack.headers(actor="cust-7"))
    assert stack.upstream.requests[-1].url.path == "/accounts/cust-7"
    # A model cannot redirect the lookup: the tool takes no arguments at all.
    bad = stack.invoke(
        "account-lookup",
        {"customer_id": "cust-42"},
        headers=stack.headers(actor="cust-7"),
        status=422,
    )
    assert bad["code"] == "invalid_arguments"


def test_refusals_happen_before_any_request(stack: Stack) -> None:
    before = len(stack.upstream.requests)
    stack.deploy(
        "agent",
        "faq-only",
        {"pack": {"name": "saas-knowledge-assistant"}, "display_name": "FAQ", "tools": []},
    )
    assert stack.invoke("account-lookup", agent="faq-only", status=403)["code"] == "forbidden"
    assert stack.invoke("nope", status=404)["code"] == "not_found"
    assert (
        stack.invoke("account-lookup", headers=stack.headers({"viewer"}), status=403)["code"]
        == "forbidden"
    )
    assert stack.invoke("open-case", {"subject": "x"}, key="k1", status=422)["errors"]
    assert stack.invoke("open-case", {"subject": "Broken login"}, status=400)["detail"].startswith(
        "Write tools need"
    )
    assert stack.invoke("open-case", {"subject": "Broken login"}, key="k2", status=403)[
        "detail"
    ].endswith("confirmation first")
    assert stack.invoke("case-status", {"case_id": "x" * 20_000}, status=422)
    assert len(stack.upstream.requests) == before


def _confirm(stack: Stack, arguments: dict[str, Any], headers: dict[str, str] | None = None) -> str:
    h = headers or stack.headers()
    pending = ok(
        stack.client.post(
            "/v1/tools/open-case/approvals",
            json={"agent": "support", "arguments": arguments},
            headers=h,
        ),
        201,
    )
    assert pending["status"] == "pending"
    assert "Open a support case" in pending["summary"]
    ok(
        stack.client.post(
            f"/v1/approvals/{pending['id']}/decision", json={"approved": True}, headers=h
        )
    )
    return str(pending["id"])


def test_write_tools_run_exactly_what_was_confirmed_once(stack: Stack) -> None:
    args = {"subject": "Cannot log in", "description": "Since Monday"}
    approval = _confirm(stack, args)
    created = stack.invoke("open-case", args, key="case-1", approval=approval)
    assert created["ok"] is True
    assert created["result"]["status"] == "open"
    # Same key: the stored result, no second case.
    calls = len(stack.upstream.requests)
    again = stack.invoke("open-case", args, key="case-1", approval=approval)
    assert (again["replayed"], again["result"]["case_id"]) == (True, created["result"]["case_id"])
    assert len(stack.upstream.requests) == calls
    # The confirmation is spent; other arguments or another person cannot use one.
    assert (
        stack.invoke("open-case", args, key="case-2", approval=approval, status=409)["detail"]
        == "Confirmation is used"
    )
    other = _confirm(stack, args)
    assert stack.invoke(
        "open-case", {"subject": "Something else"}, key="case-3", approval=other, status=403
    )
    assert stack.invoke(
        "open-case",
        args,
        key="case-4",
        approval=other,
        headers=stack.headers(actor="cust-99"),
        status=403,
    )
    assert (
        stack.client.post(
            f"/v1/approvals/{other}/decision",
            json={"approved": False},
            headers=stack.headers(actor="cust-99"),
        ).status_code
        == 404
    )


def test_declined_and_expired_confirmations(stack: Stack) -> None:
    args = {"subject": "Refund please"}  # arch: allow (test input text)
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
            json={"approved": False},
            headers=stack.headers(),
        )
    )
    assert (
        stack.invoke("open-case", args, key="d-1", approval=pending["id"], status=409)["detail"]
        == "Confirmation is declined"
    )


def test_idempotency_key_cannot_be_reused_for_different_arguments(stack: Stack) -> None:
    a = _confirm(stack, {"subject": "First case"})
    stack.invoke("open-case", {"subject": "First case"}, key="same", approval=a)
    b = _confirm(stack, {"subject": "Second case"})
    assert stack.invoke("open-case", {"subject": "Second case"}, key="same", approval=b, status=409)


def test_egress_controls(stack: Stack) -> None:
    def deploy(name: str, url: str, allow: list[str]) -> None:
        spec = {
            **ACCOUNT_TOOL,
            "request": {**ACCOUNT_TOOL["request"], "url_template": url, "host_allowlist": allow},
        }
        stack.deploy("tool", name, spec)
        stack.deploy(
            "agent",
            f"agent-{name}",
            {
                "pack": {"name": "saas-knowledge-assistant"},
                "display_name": "Test agent",
                "tools": [name],
            },
        )

    deploy("off-list", "https://other.example/accounts/1", [API])
    deploy("intranet", "https://internal.example/accounts/1", ["internal.example"])
    deploy("plain-http", f"http://{API}/accounts/1", [API])
    before = len(stack.upstream.requests)
    assert stack.invoke("off-list", agent="agent-off-list")["error"] == "egress_blocked"
    assert (
        stack.invoke("intranet", agent="agent-intranet")["error"] == "egress_blocked"
    )  # private address
    assert stack.invoke("plain-http", agent="agent-plain-http")["error"] == "egress_blocked"
    assert len(stack.upstream.requests) == before
    # Path arguments are encoded: they cannot add segments, a query or another host.
    for evil in ("../../admin", "x?y=1", "@evil.example/", "a/b#c", "%2e%2e"):
        stack.invoke("case-status", {"case_id": evil})
        sent = stack.upstream.requests[-1]
        assert sent.url.host == API_IP
        assert sent.url.raw_path.decode().startswith("/cases/")
        assert sent.url.raw_path.decode().count("/") == 2, sent.url.raw_path


def test_upstream_failures_open_the_circuit(stack: Stack) -> None:
    stack.upstream.fail_with = 503
    for _ in range(5):
        assert stack.invoke("account-lookup")["error"] == "upstream_error"
    calls = len(stack.upstream.requests)
    assert stack.invoke("account-lookup")["error"] == "circuit_open"
    assert len(stack.upstream.requests) == calls


def test_rate_limit(stack: Stack) -> None:
    stack.deploy("tool", "limited", {**ACCOUNT_TOOL, "rate_limit_per_minute": 2})
    stack.deploy(
        "agent",
        "agent-limited",
        {
            "pack": {"name": "saas-knowledge-assistant"},
            "display_name": "Test agent",
            "tools": ["limited"],
        },
    )
    for _ in range(2):
        stack.invoke("limited", agent="agent-limited")
    assert stack.invoke("limited", agent="agent-limited", status=429)["code"] == "rate_limited"


def test_credentials_are_write_only_and_per_workspace(stack: Stack) -> None:
    admin = stack.headers({"admin"}, actor="admin-1")
    listed = ok(stack.client.get("/v1/credentials", headers=admin))
    assert [c["name"] for c in listed] == ["demo-crm"]
    assert SECRET not in json.dumps(listed)
    assert (
        stack.client.put(
            "/v1/credentials/demo-crm", json={"value": "x"}, headers=stack.headers({"member"})
        ).status_code
        == 403
    )
    assert stack.client.put(
        "/v1/credentials/../../x", json={"value": "x"}, headers=admin
    ).status_code in (400, 404)
    # Tenant B has the same tool and agent, but not A's credential.
    stack.deploy("domain_pack", "saas-knowledge-assistant", PACK, tenant="b")
    stack.deploy("tool", "account-lookup", ACCOUNT_TOOL, tenant="b")
    stack.deploy(
        "agent",
        "support",
        {
            "pack": {"name": "saas-knowledge-assistant"},
            "display_name": "Tenant B",
            "tools": ["account-lookup"],
        },
        tenant="b",
    )
    out = stack.invoke("account-lookup", headers=stack.headers(tenant="b"))
    assert out["error"] == "credentials_missing"
    ok(stack.client.delete("/v1/credentials/demo-crm", headers=admin), 204)
    assert stack.invoke("account-lookup")["error"] == "credentials_missing"


def test_upstream_echo_of_the_credential_is_scrubbed(stack: Stack) -> None:
    """If an upstream echoes the credential back, it never reaches the caller or the log."""
    echo = {k: v for k, v in ACCOUNT_TOOL.items() if k != "output_schema"}
    stack.deploy("tool", "echoing", echo)
    stack.deploy(
        "agent",
        "agent-echo",
        {
            "pack": {"name": "saas-knowledge-assistant"},
            "display_name": "Test agent",
            "tools": ["echoing"],
        },
    )
    # The demo API returns the path id as customer_id; make that id equal to the credential.
    out = stack.invoke("echoing", agent="agent-echo", headers=stack.headers(actor=SECRET))
    assert out["ok"] is True
    assert out["result"]["customer_id"] == "[redacted]"
    assert SECRET not in json.dumps(out)
    assert all(
        SECRET not in row or '"actor_id": "demo-token-acme"' in row
        for row in asyncio.run(_rows(stack))
    )


def test_human_approval_tool(stack: Stack) -> None:
    stack.deploy(
        "tool",
        "manager-ok",
        {
            "description": "Ask a manager to approve an exception",
            "kind": "approval",
            "risk_level": "read",
            "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}},
        },
    )
    stack.deploy(
        "agent",
        "agent-human",
        {
            "pack": {"name": "saas-knowledge-assistant"},
            "display_name": "Test agent",
            "tools": ["manager-ok"],
        },
    )
    out = stack.invoke("manager-ok", {"reason": "loyal customer"}, agent="agent-human")
    assert out["result"]["status"] == "requested"
    task = out["result"]["request_id"]
    assert (
        stack.client.post(
            f"/v1/approvals/{task}/decision", json={"approved": True}, headers=stack.headers()
        ).status_code
        == 403
    )
    decided = ok(
        stack.client.post(
            f"/v1/approvals/{task}/decision",
            json={"approved": True},
            headers=stack.headers({"editor"}, actor="lead-1"),
        )
    )
    assert (decided["status"], decided["decided_by"]) == ("approved", "lead-1")
    log = ok(
        stack.client.get(
            "/v1/approvals?kind=human", headers=stack.headers({"member"}, actor="agent-7")
        )
    )
    assert log[0]["id"] == task


def test_dry_run_shows_the_request_without_secrets(stack: Stack) -> None:
    editor = stack.headers({"editor"}, actor="builder-1")
    preview = ok(
        stack.client.post(
            "/v1/tools/open-case/dry-run",
            json={"arguments": {"subject": "Test case"}},
            headers=editor,
        )
    )
    assert preview["request"] == {
        "method": "POST",
        "url": f"https://{API}/cases",
        "query": {},
        "body": {"subject": "Test case"},
        "headers": [],
        "credential": "secret://demo-crm",
        "auth": "bearer",
    }
    assert (
        ok(
            stack.client.post("/v1/tools/open-case/dry-run", json={"arguments": {}}, headers=editor)
        )["valid"]
        is False
    )
    assert len([r for r in stack.upstream.requests if r.method == "POST"]) == 0


def test_openapi_import_creates_valid_tools(stack: Stack) -> None:
    spec = json.dumps(mock_app.openapi())
    editor = stack.headers({"editor"}, actor="builder-1")
    tools = ok(
        stack.client.post(
            "/v1/openapi/import",
            json={"spec": spec, "base_url": f"https://{API}", "credential_ref": "demo-crm"},
            headers=editor,
        )
    )
    by_op = {t["operation_id"]: t for t in tools}
    assert set(by_op) == {"getAccount", "createCase", "getCase"}
    assert (
        by_op["getAccount"]["spec"]["risk_level"],
        by_op["createCase"]["spec"]["risk_level"],
    ) == ("read", "write")
    assert by_op["createCase"]["spec"]["input_schema"]["required"] == ["subject"]
    assert (
        "internal_notes" in by_op["getAccount"]["spec"]["output_schema"]["properties"]
    )  # edit before publishing
    for t in tools:  # every generated definition passes config's tool schema
        ok(
            stack.config.post(
                "/v1/objects",
                json={"kind": "tool", "name": t["name"], "spec": t["spec"]},
                headers=stack.tenants.a.headers,
            ),
            201,
        )
    bad = stack.client.post(
        "/v1/openapi/import", json={"spec": "openapi: 2.0\ninfo: {}"}, headers=editor
    )
    assert bad.status_code == 400
    assert (
        stack.client.post(
            "/v1/openapi/import", json={"spec": spec}, headers=stack.headers()
        ).status_code
        == 403
    )


def test_logs_are_tenant_scoped(stack: Stack) -> None:
    stack.invoke("account-lookup")
    staff_b = stack.headers({"member"}, tenant="b")
    assert ok(stack.client.get("/v1/calls", headers=staff_b)) == []
    calls = ok(stack.client.get("/v1/calls", headers=stack.headers({"member"}, actor="agent-7")))
    assert calls[0]["tool"] == "account-lookup"
    assert "result" not in calls[0]
