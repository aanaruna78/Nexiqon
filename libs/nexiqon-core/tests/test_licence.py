"""Offline licence (DV-06): signed by the vendor, verified with its public key alone."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from nexiqon_core.licence import Licence, LicenceInvalid, LicenceSettings, issue, load, verify
from nexiqon_core.testing import make_keypair

VENDOR_PRIVATE, VENDOR_PUBLIC = make_keypair()
OTHER_PRIVATE, _ = make_keypair()
KEYS = {"vendor-1": VENDOR_PUBLIC}


def licence(**over: object) -> Licence:
    base: dict[str, object] = {
        "id": "lic-1",
        "customer": "Example Co",
        "issued": date(2026, 11, 1),
        "expires": date(2027, 11, 1),
        "max_tenants": 3,
        "deployment": "air-gapped",
    }
    return Licence.model_validate({**base, **over})


def test_a_signed_licence_verifies_offline() -> None:
    token = issue(licence(), VENDOR_PRIVATE, "vendor-1")
    got = verify(token, KEYS)
    assert got.customer == "Example Co"
    assert got.max_tenants == 3


@pytest.mark.parametrize("case", ["other-key", "unknown-kid", "tampered", "garbage"])
def test_forged_or_damaged_licences_are_refused(case: str) -> None:
    good = issue(licence(), VENDOR_PRIVATE, "vendor-1")
    token = {
        "other-key": issue(licence(), OTHER_PRIVATE, "vendor-1"),
        "unknown-kid": issue(licence(), VENDOR_PRIVATE, "vendor-9"),
        "tampered": good.split(".")[0]
        + "."
        + issue(licence(max_tenants=999), OTHER_PRIVATE, "vendor-1").split(".")[1]
        + "."
        + good.split(".")[2],
        "garbage": "not-a-licence",
    }[case]
    with pytest.raises(LicenceInvalid):
        verify(token, KEYS)


def test_status_moves_from_valid_to_expired_through_the_grace_period() -> None:
    lic = licence(expires=date(2027, 1, 31), grace_days=30)
    assert lic.status(date(2026, 12, 1)) == "valid"
    assert lic.status(date(2027, 1, 15)) == "expiring"
    assert lic.status(date(2027, 1, 31)) == "expiring"
    assert lic.status(date(2027, 2, 1)) == "grace"
    assert lic.status(date(2027, 1, 31) + timedelta(days=30)) == "grace"
    assert lic.status(date(2027, 1, 31) + timedelta(days=31)) == "expired"


def test_loading_from_a_file_and_when_one_is_required(tmp_path: Path) -> None:
    path = tmp_path / "licence.jws"
    path.write_text(issue(licence(), VENDOR_PRIVATE, "vendor-1") + "\n")
    assert load(LicenceSettings(file=path, public_keys=KEYS)) is not None
    assert load(LicenceSettings()) is None  # not required, none given
    with pytest.raises(LicenceInvalid, match="needs a licence"):
        load(LicenceSettings(required=True, public_keys=KEYS))
    with pytest.raises(LicenceInvalid, match="not found"):
        load(LicenceSettings(file=tmp_path / "missing", public_keys=KEYS))
