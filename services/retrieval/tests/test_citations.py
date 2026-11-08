"""Citation verification unit tests (RT-03)."""

from __future__ import annotations

import uuid

from nexiqon_retrieval.citations import Citation, verify

P1, P2 = uuid.uuid4(), uuid.uuid4()
PASSAGES = {
    P1: "Backups run every night at 02:00 UTC and are copied to a second region.",
    P2: "Restores of large projects can take up to two hours.",
}


def test_supported_answer_keeps_all_citations() -> None:
    v = verify(
        "Backups run every night and are copied to a second region [1]. Large restores take up to two hours [2].",
        [Citation("1", P1), Citation("2", P2)],
        PASSAGES,
        0.5,
    )
    assert [c.marker for c in v.citations] == ["1", "2"]
    assert v.removed == []
    assert (v.supported_sentences, v.cited_sentences) == (2, 2)


def test_marker_kept_when_any_of_its_sentences_is_supported() -> None:
    v = verify(
        "Backups run every night [1]. Unicorns guard the backups [1].",
        [Citation("1", P1)],
        PASSAGES,
        0.5,
    )
    assert [c.marker for c in v.citations] == ["1"]


def test_unreferenced_citation_is_dropped_and_punctuation_tidied() -> None:
    v = verify("Something unrelated entirely [9].", [Citation("1", P1)], PASSAGES, 0.5)
    assert v.answer == "Something unrelated entirely."
    assert v.abstain
    assert {r.reason for r in v.removed} == {"not_referenced"}
