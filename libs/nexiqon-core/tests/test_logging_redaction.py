"""S-02: personal data and secrets never reach the logs."""

from nexiqon_core.logging import redact, redact_text


def test_values_are_masked_by_shape() -> None:
    line = (
        "mail jane.doe+x@example.com, call +44 20 7946 0958, card 4111 1111 1111 1111, "
        "key nxq_abcdefghijklmnop, Bearer abc.def.ghijklmnopqrstu, "
        "jwt eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3OCJ9.c2lnbmF0dXJlMTIzNA"
    )
    out = redact_text(line)
    for leak in ("jane.doe", "7946", "4111", "abcdefghijklmnop", "eyJzdWIi"):
        assert leak not in out, (leak, out)
    assert "[email]" in out
    assert "[key]" in out
    assert "[jwt]" in out


def test_secret_keys_are_masked_and_ids_kept() -> None:
    event = {
        "event": "login for bob@example.com",
        "tenant_id": "6f1c4b8e-2d7a-4f2e-9a1b-3c5d7e9f1a2b",
        "request_id": "abc123",
        "password": "hunter2",
        "headers": {"Authorization": "Bearer xyz", "accept": "json"},
        "attempts": 3,
        "items": ["ok", "x@y.io"],
    }
    out = redact(None, "info", dict(event))
    assert out["event"] == "login for [email]"
    assert out["password"] == "[redacted]"
    assert out["headers"] == {"Authorization": "[redacted]", "accept": "json"}
    assert out["items"] == ["ok", "[email]"]
    assert out["tenant_id"] == event["tenant_id"]
    assert out["attempts"] == 3


def test_ids_times_and_numbers_stay_readable() -> None:
    for safe in (
        "01a1f3e9-224d-7000-b7b8-d8674c25469b",
        "6f1c4b8e-2d7a-4f2e-9a1b-3c5d7e9f1a2b",
        "2026-11-19T13:03:26.759417Z",
        "took 1234 ms for 56 rows",
        "v1.27.0",
    ):
        assert redact_text(safe) == safe
