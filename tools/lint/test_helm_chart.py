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
