"""Assistant scoping must cover existing conversation reads."""

from nexiqon_core.tenancy import CONTEXT_HEADER, TenantContext

pytest_plugins = ["services.conversation.tests.conftest"]


def test_scoped_member_api_key_must_not_read_other_assistants_conversations(stack):
    created = stack.start(headers=stack.headers(actor="ordinary-user"), agent="support")
    stack.say(
        created["id"],
        "How do I invite a teammate?",
        headers=stack.headers(actor="ordinary-user"),
    )
    ctx = TenantContext(
        stack.tenants.a.context.tenant_id,
        "key:billing-only",
        "api_key",
        frozenset({"member"}),
        agents=frozenset({"billing"}),
    )
    headers = {CONTEXT_HEADER: stack.tenants.issuer.issue(ctx)}
    r = stack.client.get("/v1/conversations/" + created["id"], headers=headers)
    listed = stack.client.get("/v1/conversations", headers=headers)
    print(
        "billing-only key reading support conversation:",
        r.status_code,
        "messages:",
        len(r.json().get("messages", [])),
        "list count:",
        len(listed.json()),
    )
    assert r.status_code in (403, 404)
    assert all(c["agent"] == "billing" for c in listed.json())


def test_restricted_answer_history_must_not_be_sent_to_an_internal_model_call(stack):
    stack.fakes.passages[0]["classification"] = "restricted"
    stack.fakes.answer = (
        "RESTRICTED-QA-ALPHA: Open Settings, then Members, and choose Invite [1]."
    )
    c = stack.start()
    first = stack.say(c["id"], "How do I invite a teammate?")
    assert first["reply"] is not None, first
    grounded = stack.fakes.chats("answer")[-1]
    assert grounded["classification"] == "restricted"
    stack.say(c["id"], "hi")
    smalltalk = stack.fakes.chats("smalltalk")[-1]
    leaked = any(
        "RESTRICTED-QA-ALPHA" in str(m.get("content", ""))
        for m in smalltalk["messages"]
    )
    print(
        "trusted prior answer label:",
        grounded["classification"],
        "next call label:",
        smalltalk["classification"],
        "profile:",
        smalltalk["profile"],
        "restricted history included:",
        leaked,
    )
    assert not (leaked and smalltalk["classification"] != "restricted")
