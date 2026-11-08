from nexiqon_model_gateway.redaction import Redactor


def test_redacts_and_restores_consistently() -> None:
    r = Redactor()
    text = (
        "Mail jane.doe@example.com or +44 20 7946 0958; card 4111 1111 1111 1111. "
        "Again: jane.doe@example.com"
    )
    red = r.redact(text)
    assert "jane.doe@example.com" not in red
    assert "4111" not in red
    assert "7946" not in red
    assert red.count("[EMAIL_1]") == 2
    assert "[CARD_1]" in red
    assert "[PHONE_1]" in red
    assert r.restore(red) == text


def test_leaves_dates_ids_and_invalid_cards_alone() -> None:
    r = Redactor()
    text = "Released 2026-11-08, order 12345, reference 4111 1111 1111 1112, version 3.12.15"
    assert r.redact(text) == text


def test_restores_inside_tool_arguments() -> None:
    r = Redactor()
    r.redact("contact a@b.co")
    assert r.restore_value({"to": ["[EMAIL_1]"], "n": 1}) == {"to": ["a@b.co"], "n": 1}
    assert r.redact_value({"to": "a@b.co"}) == {"to": "[EMAIL_1]"}
    assert r.restore("[EMAIL_9] unknown stays") == "[EMAIL_9] unknown stays"
