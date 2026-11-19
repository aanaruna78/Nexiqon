"""Staff-only access diagnostics must not be exposed to widget callers."""

pytest_plugins = ["services.retrieval.tests.conftest"]


def test_widget_search_must_not_count_hidden_restricted_sources(stack):
    stack.index(
        "# Payroll\n\n## Backups\n\nPayroll backups use a separate encryption key.",
        "upload://payroll-qa.md",
        acl=["payroll"],
        classification="restricted",
    )
    headers = stack.headers({"end_user"}, actor_type="widget")
    r = stack.client.post(
        "/v1/search",
        json={
            "query": "Payroll backups use a separate encryption key",
            "collection_ids": [str(stack.collection)],
            "explain_access": True,
        },
        headers=headers,
    )
    print(
        "widget search status:",
        r.status_code,
        "visible:",
        len(r.json().get("passages", [])),
        "hidden:",
        r.json().get("hidden"),
    )
    if r.status_code == 200:
        assert r.json().get("hidden") is None
    else:
        assert r.status_code == 403
