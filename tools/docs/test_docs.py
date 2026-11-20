"""The docs site (D-01) stays in step with the code it documents."""

from __future__ import annotations

from tools.docs.api_reference import OUT, pages


def test_the_api_reference_matches_the_contracts() -> None:
    expected = pages()
    assert sorted(p.name for p in OUT.glob("*.md") if p.name != "index.md") == sorted(expected)
    for name, text in expected.items():
        assert (OUT / name).read_text() == text, (
            f"run: uv run python -m tools.docs.api_reference ({name})"
        )


def test_internal_endpoints_are_not_documented() -> None:
    for name, text in pages().items():
        assert "/internal/" not in text, name
        assert "/_lifecycle" not in text, name
    assert "authz.md" not in pages()
    assert "model-gateway.md" not in pages()
