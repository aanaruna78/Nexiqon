"""Hybrid search (RT-02), filter-before-rank, small-to-big (RT-07), abstain, rerank, citations (RT-03)."""

from __future__ import annotations

import uuid

import pytest

from nexiqon_retrieval.search import SEPARATOR, SearchRequest
from nexiqon_retrieval.store import Filters

from .conftest import SearchStack

pytestmark = pytest.mark.integration

GUIDE = """# Operations Guide

## Backups

Backups run every night at 02:00 UTC.

Each backup is kept for 35 days and copied to a second region.

## Restores

To restore, open the console and choose Restore from backup.

Restores of large projects can take up to two hours.

## Monitoring

Dashboards show error rates and latency for every service.
"""

SECRET = """# Payroll Handbook

## Backups of payroll data

Payroll backups run every night at 02:00 UTC and are encrypted with a separate key.
"""


def sections(result: dict) -> list[list[str]]:  # type: ignore[type-arg]
    return [p["heading_path"] for p in result["passages"]]


def test_hybrid_search_expands_to_sections_with_citations(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://ops-guide.md", max_tokens=20)
    r = stack.search("When do backups run every night?")
    top = r["passages"][0]
    assert top["heading_path"] == ["Backups"]
    assert top["kind"] == "section"
    # Small-to-big: both chunks of the section, though only one matched best.
    assert "kept for 35 days" in top["text"]
    assert "02:00 UTC" in top["text"]
    assert top["citation"] == f"Operations Guide{SEPARATOR}Backups"
    assert len(top["chunk_ids"]) == 2
    assert r["embedding_model"] == "hash-ngram-1024"
    assert r["abstain"] is False
    assert set(r["timings_ms"]) >= {"embed", "vector", "keyword", "fuse", "expand", "total"}
    flat = stack.search("When do backups run every night?", small_to_big=False)
    assert flat["passages"][0]["kind"] == "chunk"
    assert "kept for 35 days" not in flat["passages"][0]["text"]


def test_keyword_search_finds_exact_terms_and_pages_are_cited(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://ops-guide.md", pages=True)
    r = stack.search("Restore from backup console")
    assert r["passages"][0]["heading_path"] == ["Restores"]
    assert ", p." in r["passages"][0]["citation"] or ", pp." in r["passages"][0]["citation"]


def test_access_groups_filter_before_ranking(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://ops-guide.md")
    stack.index(SECRET, "upload://payroll.md", acl=["payroll"])
    query = "payroll backups encrypted with a separate key"
    outsider = stack.search(query, headers=stack.headers({"member"}, {"engineering"}))
    assert all("payroll" not in p["source_uri"] for p in outsider["passages"])
    insider = stack.search(query, headers=stack.headers({"member"}, {"payroll"}))
    assert insider["passages"][0]["source_uri"] == "upload://payroll.md"
    admin = stack.search(query, headers=stack.headers({"admin"}))
    assert admin["passages"][0]["source_uri"] == "upload://payroll.md"


def test_widgets_never_see_confidential_content(stack: SearchStack) -> None:
    stack.index(SECRET, "upload://payroll.md", classification="confidential")
    stack.index(GUIDE, "upload://ops-guide.md", classification="public")
    widget = stack.headers({"end_user"}, actor_type="widget")
    r = stack.search("payroll backups encrypted", headers=widget)
    assert all(p["source_uri"] == "upload://ops-guide.md" for p in r["passages"])
    member = stack.search("payroll backups encrypted")
    assert member["passages"][0]["source_uri"] == "upload://payroll.md"


def test_other_embedding_models_and_tenants_are_invisible(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://old.md", model="old-model")  # not yet reindexed
    r = stack.search("When do backups run every night?")
    # Keyword search may still find it, but never through a foreign vector space.
    assert r["evidence_score"] == 0.0
    assert r["abstain"] is True
    stack.index(GUIDE, "upload://b.md", tenant="b")
    assert all(
        p["source_uri"] != "upload://b.md" for p in stack.search("backups").get("passages", [])
    )
    other = stack.search("backups", headers=stack.headers({"member"}, tenant="b"))
    assert all(p["source_uri"] == "upload://b.md" for p in other["passages"])


def test_abstains_on_unrelated_questions(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://ops-guide.md")
    r = stack.search("zebra migration patterns in savannah", retrieval_profile="standard")
    assert r["abstain"] is True


def test_rerank_reorders_and_sets_evidence(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://ops-guide.md", max_tokens=20)
    stack.models.rerank_enabled = True
    r = stack.search("how long can restores of large projects take", rerank=True)
    assert r["reranked"] is True
    assert r["passages"][0]["heading_path"] == ["Restores"]
    assert "rerank" in r["timings_ms"]
    stack.models.rerank_enabled = False  # profile without a reranker: search proceeds
    assert stack.search("restores", rerank=True)["reranked"] is False


def test_duplicate_text_is_returned_once(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://copy-1.md")
    stack.index(GUIDE, "upload://copy-2.md")
    r = stack.search("Dashboards show error rates and latency", small_to_big=False)
    texts = [p["text"] for p in r["passages"]]
    assert len(texts) == len(set(texts))


def test_citation_verification_strips_fabrications(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://ops-guide.md")
    stack.index(SECRET, "upload://payroll.md", acl=["payroll"])
    r = stack.search("When do backups run?")
    backups = next(p for p in r["passages"] if p["heading_path"] == ["Backups"])
    payroll = stack.search("payroll backups", headers=stack.headers({"admin"}))["passages"][0]
    answer = (
        "Backups run every night at 02:00 UTC [1]. "
        "Backups are stored on the moon [2]. "
        "Payroll data uses a separate key [3]. "
        "Restores are instant [4]."
    )
    body = {
        "answer": answer,
        "collection_ids": [str(stack.collection)],
        "citations": [
            {"marker": "1", "passage_id": backups["id"], "quote": "every night at 02:00 UTC"},
            {"marker": "2", "passage_id": backups["id"], "quote": "stored on the moon"},
            {"marker": "3", "passage_id": payroll["id"]},  # not visible to this member
            {"marker": "4", "passage_id": str(uuid.uuid4())},
        ],
    }
    out = stack.client.post(
        "/v1/citations/verify", json=body, headers=stack.headers({"member"})
    ).json()
    assert [c["marker"] for c in out["citations"]] == ["1"]
    assert {(x["marker"], x["reason"]) for x in out["removed"]} == {
        ("2", "quote_not_found"),
        ("3", "unknown_passage"),
        ("4", "unknown_passage"),
    }
    assert "[1]" in out["answer"]
    assert "[2]" not in out["answer"]
    assert out["abstain"] is False
    unsupported = stack.client.post(
        "/v1/citations/verify",
        json={
            "answer": "Penguins enjoy cold weather [1].",
            "collection_ids": [str(stack.collection)],
            "citations": [{"marker": "1", "passage_id": backups["id"]}],
        },
        headers=stack.headers({"member"}),
    ).json()
    assert unsupported["removed"] == [{"marker": "1", "reason": "unsupported"}]
    assert unsupported["abstain"] is True


def test_permissions(stack: SearchStack) -> None:
    body = {"query": "x", "collection_ids": [str(stack.collection)]}
    assert stack.client.post("/v1/search", json=body).status_code == 401
    assert (
        stack.client.post("/v1/search", json=body, headers=stack.headers({"viewer"})).status_code
        == 403
    )


def test_grounded_answer_cites_verified_passages(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://ops-guide.md")
    r = stack.client.post(
        "/v1/answer",
        json={
            "query": "How long is each backup kept?",
            "collection_ids": [str(stack.collection)],
            "retrieval_profile": "dev-offline",
        },
        headers=stack.headers({"member"}),
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["abstained"] is False
    assert "35 days" in out["answer"]
    assert out["citations"][0]["citation"].endswith("Backups")
    assert out["citations"][0]["passage_id"] == out["search"]["passages"][0]["id"]
    assert "generate" in out["search"]["timings_ms"]
    chat = next(c for c in stack.models.calls if c["op"] == "chat")
    prompt = chat["messages"][1]["content"]
    assert prompt.startswith("Sources:\n\n[1] Operations Guide")
    assert prompt.endswith("Question: How long is each backup kept?")


def test_answer_with_fabricated_citations_abstains(stack: SearchStack) -> None:
    stack.index(GUIDE, "upload://ops-guide.md")
    stack.models.answer = "Backups are stored on the moon by penguins [1]. See also [7]."
    out = stack.client.post(
        "/v1/answer",
        json={
            "query": "Where are backups stored?",
            "collection_ids": [str(stack.collection)],
            "retrieval_profile": "dev-offline",
        },
        headers=stack.headers({"member"}),
    ).json()
    assert out["abstained"] is True
    assert out["citations"] == []
    assert {x["reason"] for x in out["removed"]} == {"unsupported"}
    assert "[1]" not in out["answer"]
    assert "[7]" not in out["answer"]


def test_answer_abstains_without_evidence_and_skips_the_model(stack: SearchStack) -> None:
    out = stack.client.post(
        "/v1/answer",
        json={"query": "anything at all", "collection_ids": [str(stack.collection)]},
        headers=stack.headers({"member"}),
    ).json()
    assert (out["abstained"], out["reason"], out["answer"]) == (True, "no_passages", None)
    assert not any(c["op"] == "chat" for c in stack.models.calls)


# ---------------------------------------------------------------- QA 2026-11-09 regressions


def _answer(stack: SearchStack, query: str, **extra: object) -> dict:  # type: ignore[type-arg]
    body = {
        "query": query,
        "collection_ids": [str(stack.collection)],
        "retrieval_profile": "dev-offline",
        **extra,
    }
    r = stack.client.post("/v1/answer", json=body, headers=stack.headers({"member"}))
    assert r.status_code == 200, r.text
    out: dict = r.json()  # type: ignore[type-arg]
    return out


def test_qa2_01_model_calls_carry_the_strictest_source_label(stack: SearchStack) -> None:
    stack.index(SECRET, "upload://payroll.md", classification="restricted")
    stack.index(GUIDE, "upload://ops-guide.md", classification="public")
    _answer(stack, "Payroll backups use a separate encryption key", classification="internal")
    chat = [c for c in stack.models.calls if c["op"] == "chat"]
    assert chat
    assert {c["classification"] for c in chat} == {"restricted"}  # not the caller's "internal"
    stack.models.calls.clear()
    stack.search("payroll backups encrypted separate key", rerank=True, classification="public")
    rerank = [c for c in stack.models.calls if c["op"] == "rerank"]
    assert [c["classification"] for c in rerank] == ["restricted"]


def test_qa2_01_keyword_candidates_from_another_vector_space_keep_their_label(
    stack: SearchStack,
) -> None:
    stack.index(
        SECRET, "upload://payroll.md", classification="restricted", model="onprem-only-model"
    )
    stack.search("payroll backups encrypted separate key", rerank=True)
    rerank = [c for c in stack.models.calls if c["op"] == "rerank"]
    assert [c["classification"] for c in rerank] == ["restricted"]


def test_qa2_01_refused_labels_never_reach_the_model(stack: SearchStack) -> None:
    stack.index(SECRET, "upload://payroll.md", classification="restricted")
    stack.models.refuse = {"restricted"}
    stack.models.rerank_enabled = True
    searched = stack.search("payroll backups encrypted separate key", rerank=True)
    assert searched["reranked"] is False  # skipped, results still returned to the authorised reader
    assert searched["passages"][0]["classification"] == "restricted"
    out = _answer(stack, "Payroll backups use a separate encryption key")
    assert (out["abstained"], out["reason"], out["answer"]) == (True, "sensitivity", None)


def test_qa2_06_context_cap_holds_for_the_first_passage(stack: SearchStack) -> None:
    stack.index(
        "# Guide\n\n## Policy\n\n" + "Backups run every night. " * 60,
        "upload://large.md",
        max_tokens=400,
    )
    for cap in (256, 300):
        r = stack.client.portal.call(  # type: ignore[union-attr]
            stack.client.app.state.searcher.search,  # type: ignore[attr-defined]
            stack.tenants.a.context.tenant_id,
            stack.tenants.a.token,
            SearchRequest(
                query="Backups run every night",
                filters=Filters([stack.collection]),
                profile={"small_to_big": {"max_context_tokens": cap}},
                model_profile="dev-offline",
                classification="internal",
            ),
        )
        assert sum(p.token_count for p in r.passages) <= cap
        assert r.passages[0].truncated is True
        assert r.passages[0].text.endswith("\u2026")
