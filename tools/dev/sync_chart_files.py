"""Copy the files the Helm chart ships from their sources (the chart cannot read outside itself).

uv run python tools/dev/sync_chart_files.py          # copy
uv run python tools/dev/sync_chart_files.py --check  # fail if any copy is stale (CI test)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy" / "helm" / "nexiqon" / "files"
SOURCES = {
    "policies/authz.rego": ROOT / "services/authz/policies/nexiqon/authz.rego",
    "flags.json": ROOT / "deploy/compose/flags/flags.json",
    "seaweedfs-s3.json": ROOT / "deploy/compose/seaweedfs-s3.json",
    "keycloak-realm.json": ROOT / "deploy/compose/keycloak/nexiqon-realm.json",
}


def stale() -> list[str]:
    return [
        name
        for name, src in SOURCES.items()
        if not (CHART / name).exists() or (CHART / name).read_bytes() != src.read_bytes()
    ]


def main() -> int:
    if "--check" in sys.argv:
        problems = stale()
        for name in problems:
            print(f"stale chart file: {name} (run tools/dev/sync_chart_files.py)")
        return 1 if problems else 0
    for name, src in SOURCES.items():
        target = CHART / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
        print(f"copied {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
