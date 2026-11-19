"""The Helm chart (DV-02) stays in step with the repository it packages."""

from __future__ import annotations

from pathlib import Path

import yaml

from tools.dev.sync_chart_files import stale

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy" / "helm" / "nexiqon"


def test_chart_files_match_their_sources() -> None:
    assert stale() == [], "run tools/dev/sync_chart_files.py"


def test_chart_groups_match_deploy_groups() -> None:
    groups = yaml.safe_load((ROOT / "deploy/groups.yaml").read_text())["groups"]
    values = yaml.safe_load((CHART / "values.yaml").read_text())["groups"]
    assert {k: (g["plane"], g["services"]) for k, g in groups.items()} == {
        k: (g["plane"], g["services"]) for k, g in values.items()
    }


def test_only_a_services_own_group_mounts_its_identity_key() -> None:
    values = yaml.safe_load((CHART / "values.yaml").read_text())["groups"]
    owners = {f"identity-{svc}.yaml": name for name, g in values.items() for svc in g["services"]}
    for name, g in values.items():
        for f in g["keyFiles"]:
            if f.startswith("identity-"):
                assert owners[f] == name, f"{name} mounts {f}"


def test_signing_private_keys_stay_with_identity_and_config() -> None:
    """secrets.yaml holds identity's and config's signing private keys: no other group mounts it."""
    values = yaml.safe_load((CHART / "values.yaml").read_text())["groups"]
    for name, g in values.items():
        holds = {"identity", "config"} & set(g["services"])
        if "secrets.yaml" in g["keyFiles"]:
            assert holds, f"{name} mounts signing private keys it does not need"
        else:
            assert "public-keys.yaml" in g["keyFiles"], f"{name} cannot verify tokens"


def test_the_hybrid_data_plane_holds_no_control_plane_keys_or_services() -> None:
    """DV-04: the customer's cluster runs data-plane services only, with verification keys only."""
    profile = yaml.safe_load((CHART / "values/hybrid-data.yaml").read_text())
    base = yaml.safe_load((CHART / "values.yaml").read_text())["groups"]
    groups = {k: {**base.get(k, {}), **g} for k, g in profile["groups"].items()}
    groups = {**{k: g for k, g in base.items() if k not in groups}, **groups}
    running = {k: g for k, g in groups.items() if g.get("enabled", True)}
    assert all(g["plane"] == "data" for g in running.values())
    services = {s for g in running.values() for s in g["services"]}
    assert not services & {"identity", "config", "audit", "governance", "evaluation", "metering"}
    assert "config-mirror" in services
    for g in running.values():
        assert "secrets.yaml" not in g["keyFiles"]
    assert profile["controlPlane"]["host"]
