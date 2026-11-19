"""Independent Phase 3 tool authorization acceptance cases."""

import importlib

from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext

pytest_plugins = ["services.tool-gateway.tests.conftest"]


def test_idempotency_results_must_be_scoped_to_the_caller(stack):
    a = stack.invoke(
        "account-lookup",
        headers=stack.headers(actor="customer-a"),
        key="shared-request-id",
    )
    b = stack.invoke(
        "account-lookup",
        headers=stack.headers(actor="customer-b"),
        key="shared-request-id",
    )
    print(
        "different callers shared key: replayed=",
        b["replayed"],
        "same result=",
        a["result"] == b["result"],
        "upstream calls=",
        len(stack.upstream.requests),
    )
    assert not b["replayed"], "Customer B received customer A account response"


def test_agent_restricted_key_must_not_invoke_a_different_assistants_tools(stack):
    ctx = TenantContext(
        stack.tenants.a.context.tenant_id,
        "key:restricted",
        "api_key",
        frozenset({"end_user"}),
        agents=frozenset({"billing"}),
    )
    headers = {CONTEXT_HEADER: stack.tenants.issuer.issue(ctx)}
    r = stack.client.post(
        "/v1/tools/account-lookup/invoke",
        json={"agent": "support", "arguments": {}},
        headers=headers,
    )
    print("billing-only key invoking support tool:", r.status_code, r.json().get("ok"))
    assert r.status_code == 403


def test_pack_raised_write_risk_must_require_confirmation(stack):
    fixture = importlib.import_module("services.tool-gateway.tests.conftest")
    spec = {**fixture.CASE_TOOL, "risk_level": "read", "confirmation": "never"}
    stack.deploy("tool", "create-ticket", spec)
    stack.deploy(
        "agent",
        "ticket-desk",
        {
            "pack": {"name": "saas-knowledge-assistant"},
            "display_name": "QA desk",
            "tools": ["create-ticket"],
        },
    )
    r = stack.client.post(
        "/v1/tools/create-ticket/invoke",
        json={
            "agent": "ticket-desk",
            "arguments": {"subject": "QA synthetic case"},
            "idempotency_key": "qa-effective-risk",
        },
        headers=stack.headers(),
    )
    print(
        "pack write risk without approval:",
        r.status_code,
        r.json().get("ok"),
        "upstream calls:",
        len(stack.upstream.requests),
    )
    assert r.status_code == 403
