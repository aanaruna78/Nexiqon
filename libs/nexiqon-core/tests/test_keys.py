"""Installation keys (nexiqon-keys): complete, consistent, private, and never overwritten."""

from __future__ import annotations

from pathlib import Path

import yaml

from nexiqon_core.keys import SERVICE_IDENTITIES, generate, public_of


def test_generates_every_file_and_the_public_halves_match(tmp_path: Path) -> None:
    generate(tmp_path)
    secrets = yaml.safe_load((tmp_path / "secrets.yaml").read_text())
    public = yaml.safe_load((tmp_path / "public-keys.yaml").read_text())
    kid = secrets["signing"]["active_kid"]
    assert public["context_token"]["public_keys"][kid] == public_of(
        secrets["signing"]["private_keys"][kid]
    )
    snap = secrets["snapshot_signing"]["active_kid"]
    assert public["snapshot_public_keys"][snap] == public_of(
        secrets["snapshot_signing"]["private_keys"][snap]
    )
    assert "PRIVATE" not in (tmp_path / "public-keys.yaml").read_text()
    services = yaml.safe_load((tmp_path / "service-keys.yaml").read_text())["context_token"]
    assert set(services["service_keys"].values()) == set(SERVICE_IDENTITIES)
    for service, settings_key in SERVICE_IDENTITIES.items():
        ident = yaml.safe_load((tmp_path / f"identity-{service}.yaml").read_text())[settings_key]
        assert services["public_keys"][ident["key_id"]] == public_of(ident["private_key"])
    assert (tmp_path / "secrets.yaml").stat().st_mode & 0o007 == 0  # not world-readable


def test_running_again_keeps_existing_keys(tmp_path: Path) -> None:
    generate(tmp_path)
    before = (
        (tmp_path / "secrets.yaml").read_text(),
        (tmp_path / "identity-channel.yaml").read_text(),
    )
    (tmp_path / "identity-ingestion.yaml").unlink()  # a lost file is recreated
    written = generate(tmp_path)
    assert "secrets.yaml" not in written
    assert "identity-ingestion.yaml" in written
    after = (
        (tmp_path / "secrets.yaml").read_text(),
        (tmp_path / "identity-channel.yaml").read_text(),
    )
    assert before == after
