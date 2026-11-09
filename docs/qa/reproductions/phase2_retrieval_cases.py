"""Additional Phase 2 QA acceptance cases. Run explicitly with pytest."""

import uuid

from nexiqon_retrieval.citations import Citation, verify
from nexiqon_retrieval.search import SearchRequest
from nexiqon_retrieval.store import Filters

pytest_plugins = ["services.retrieval.tests.conftest"]


def test_sensitive_answer_must_not_use_caller_supplied_lower_classification(stack, monkeypatch):
    stack.index(
        "# Restricted guide\n\n## Backups\n\nPayroll backups use a separate encryption key.",
        "upload://restricted.md",
        classification="restricted",
    )
    captured = []
    original = stack.models.chat

    async def spy(token, profile, classification, messages, max_tokens):
        captured.append((profile, classification, messages[-1]["content"]))
        return await original(token, profile, classification, messages, max_tokens)

    monkeypatch.setattr(stack.models, "chat", spy)
    r = stack.client.post(
        "/v1/answer",
        json={
            "query": "Payroll backups use a separate encryption key",
            "collection_ids": [str(stack.collection)],
            "retrieval_profile": "dev-offline",
            "model_profile": "cloud-frontier",
            "classification": "internal",
        },
        headers=stack.headers({"member"}),
    )
    assert r.status_code == 200, r.text
    print(
        "answer status:",
        r.status_code,
        "model calls:",
        [(p, c, "Payroll backups" in prompt) for p, c, prompt in captured],
    )
    assert not any(
        profile == "cloud-frontier"
        and classification != "restricted"
        and "Payroll backups" in prompt
        for profile, classification, prompt in captured
    ), "Restricted passage sent to cloud-selected chat as internal"


def test_hidden_document_outline_is_not_disclosed(stack):
    doc = stack.index(
        "# Secret acquisition\n\n## Confidential deal price\n\nThe acquisition costs ten million.",
        "upload://restricted.md",
        acl=["legal"],
        classification="restricted",
    )
    headers = stack.headers({"member"}, {"engineering"})
    assert stack.search("acquisition costs", headers=headers)["passages"] == []
    r = stack.client.get(f"/v1/index/documents/{doc}/outline", headers=headers)
    print("hidden outline:", r.status_code, r.text)
    assert r.status_code in (403, 404), "Hidden document titles and headings disclosed"


def test_repeated_marker_does_not_validate_an_unsupported_occurrence():
    passage = uuid.uuid4()
    checked = verify(
        "Backups run every night [1]. Penguins pilot spaceships [1].",
        [Citation("1", passage)],
        {passage: "Backups run every night."},
        0.5,
    )
    print(
        "checked answer:",
        checked.answer,
        "supported:",
        checked.supported_sentences,
        "cited:",
        checked.cited_sentences,
    )
    assert "Penguins pilot spaceships [1]" not in checked.answer


def test_section_expansion_honors_context_cap(stack):
    stack.index(
        "# Guide\n\n## Policy\n\n" + "Backups run every night. " * 60,
        "upload://large.md",
        max_tokens=400,
    )
    req = SearchRequest(
        query="Backups run every night",
        filters=Filters([stack.collection], ["internal"], []),
        profile={"small_to_big": {"max_context_tokens": 256}},
        model_profile="cloud-frontier",
        classification="internal",
    )
    r = stack.client.portal.call(
        stack.client.app.state.searcher.search,
        stack.tenants.a.context.tenant_id,
        stack.tenants.a.token,
        req,
    )
    print("passage tokens:", [p.token_count for p in r.passages], "cap:", 256)
    assert sum(p.token_count for p in r.passages) <= 256


def test_sensitive_keyword_candidates_must_not_rerank_as_internal(stack, monkeypatch):
    stack.index(
        "# Secret guide\n\n## Payroll\n\nPayroll backups use a separate encryption key.",
        "upload://restricted-rerank.md",
        classification="restricted",
        model="onprem-only-model",
    )
    captured = []
    original = stack.models.rerank

    async def spy(token, profile, classification, query, documents, top_n):
        captured.append((profile, classification, list(documents)))
        return await original(token, profile, classification, query, documents, top_n)

    monkeypatch.setattr(stack.models, "rerank", spy)
    r = stack.client.post(
        "/v1/search",
        json={
            "query": "Payroll backups separate encryption key",
            "collection_ids": [str(stack.collection)],
            "model_profile": "cloud-frontier",
            "classification": "internal",
            "rerank": True,
        },
        headers=stack.headers({"member"}),
    )
    assert r.status_code == 200, r.text
    print(
        "rerank profile/classification/sensitive_content:",
        [(p, c, any("Payroll backups" in d for d in ds)) for p, c, ds in captured],
    )
    assert not any(
        p == "cloud-frontier" and c != "restricted" and any("Payroll backups" in d for d in ds)
        for p, c, ds in captured
    )
