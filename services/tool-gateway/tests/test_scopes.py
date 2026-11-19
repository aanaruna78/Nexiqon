"""QA3-01..03 regressions: replay identity, assistant-scoped keys, effective risk and confirmation."""

from __future__ import annotations

import yaml

from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext

from .conftest import CASE_TOOL, PACK, Stack, ok


def scoped(stack: Stack, agents: set[str], roles: set[str] | None = None) -> dict[str, str]:
    ctx = TenantContext(
        stack.tenants.a.context.tenant_id,
        "key:scoped",
        "api_key",
        frozenset(roles or {"end_user"}),
        agents=frozenset(agents),
    )
    return {CONTEXT_HEADER: stack.tenants.issuer.issue(ctx)}


def test_replays_belong_to_their_caller_and_assistant(stack: Stack) -> None:
    a = stack.invoke("account-lookup", headers=stack.headers(actor="customer-a"), key="k-1")
    again = stack.invoke("account-lookup", headers=stack.headers(actor="customer-a"), key="k-1")
    assert again["replayed"] is True  # the same caller retrying still gets the stored result
    assert again["result"] == a["result"]
    b = stack.invoke("account-lookup", headers=stack.headers(actor="customer-b"), key="k-1")
    assert b["replayed"] is False  # someone else's key never returns another person's data
    assert len(stack.upstream.requests) == 2


def test_keys_limited_to_assistants_stay_inside_them(stack: Stack) -> None:
    billing_only = scoped(stack, {"billing"})
    body = {"agent": "support", "arguments": {}}
    assert (
        stack.client.post(
            "/v1/tools/account-lookup/invoke", json=body, headers=billing_only
        ).status_code
        == 403
    )
    assert (
        stack.client.post(
            "/v1/tools/open-case/approvals",
            json={**body, "arguments": {"subject": "Help me"}},
            headers=billing_only,
        ).status_code
        == 403
    )
    assert (
        stack.client.get(
            "/v1/tools/account-lookup", params={"agent": "support"}, headers=billing_only
        ).status_code
        == 403
    )
    assert stack.client.get("/v1/tools/account-lookup", headers=billing_only).status_code == 403
    admin_scoped = scoped(stack, {"billing"}, {"admin"})
    assert (
        stack.client.post(
            "/v1/tools/account-lookup/dry-run", json={"arguments": {}}, headers=admin_scoped
        ).status_code
        == 403
    )
    assert stack.client.get("/v1/credentials", headers=admin_scoped).status_code == 403
    # Logs only show what the key's assistants did.
    stack.invoke("account-lookup", headers=stack.headers({"admin"}))
    calls = ok(stack.client.get("/v1/calls", headers=admin_scoped))
    assert calls == []
    support_admin = scoped(stack, {"support"}, {"admin"})
    assert ok(stack.client.get("/v1/calls", headers=support_admin))
    assert stack.invoke("account-lookup", headers=scoped(stack, {"support"}))["ok"] is True


def test_the_stricter_of_pack_and_definition_decides_confirmation(stack: Stack) -> None:
    pack = yaml.safe_load(PACK)
    pack["metadata"]["name"] = "strict-pack"
    pack["spec"]["tools"] = [
        {"name": "account-lookup", "risk_level": "read", "confirmation": "always"},
        {"name": "lenient-case", "risk_level": "write", "confirmation": "always"},
    ]
    stack.deploy("domain_pack", "strict-pack", yaml.safe_dump(pack))
    # The definition claims a harmless read; the pack says it writes.
    stack.deploy(
        "tool", "lenient-case", {**CASE_TOOL, "risk_level": "read", "confirmation": "never"}
    )
    stack.deploy(
        "agent",
        "strict",
        {
            "pack": {"name": "strict-pack"},
            "display_name": "Strict desk",
            "tools": ["account-lookup", "lenient-case"],
        },
    )
    described = ok(
        stack.client.get(
            "/v1/tools/lenient-case", params={"agent": "strict"}, headers=stack.headers()
        )
    )
    assert (described["risk_level"], described["needs_confirmation"]) == ("write", True)
    body = {
        "agent": "strict",
        "arguments": {"subject": "Synthetic case"},
        "idempotency_key": "strict-1",
    }
    assert (
        stack.client.post(
            "/v1/tools/lenient-case/invoke", json=body, headers=stack.headers()
        ).status_code
        == 403
    )
    read_but_confirm = ok(
        stack.client.get(
            "/v1/tools/account-lookup", params={"agent": "strict"}, headers=stack.headers()
        )
    )
    assert (read_but_confirm["risk_level"], read_but_confirm["needs_confirmation"]) == (
        "read",
        True,
    )
    refused = stack.client.post(
        "/v1/tools/account-lookup/invoke",
        json={"agent": "strict", "arguments": {}},
        headers=stack.headers(),
    )
    assert refused.status_code == 403
    assert stack.upstream.requests == []
    # With the user's confirmation the call goes through, exactly as confirmed.
    approval = ok(
        stack.client.post(
            "/v1/tools/lenient-case/approvals",
            json={"agent": "strict", "arguments": {"subject": "Synthetic case"}},
            headers=stack.headers(),
        ),
        201,
    )
    ok(
        stack.client.post(
            f"/v1/approvals/{approval['id']}/decision",
            json={"approved": True},
            headers=stack.headers(),
        )
    )
    done = ok(
        stack.client.post(
            "/v1/tools/lenient-case/invoke",
            json={**body, "approval_id": approval["id"]},
            headers=stack.headers(),
        )
    )
    assert done["ok"] is True
