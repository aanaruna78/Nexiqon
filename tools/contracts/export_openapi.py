"""Export contracts: each service's OpenAPI document (contracts/openapi/<service>.json) and the
configuration JSON Schemas owned by the config service (contracts/schemas/config/<kind>.schema.json).

    python -m tools.contracts.export_openapi          # write
    python -m tools.contracts.export_openapi --check  # fail if contracts are stale (CI)

Contracts are reviewed in PRs before implementation (PLAN.md §6, rule 1). Breaking-change detection
against main runs in CI with oasdiff.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nexiqon_core.directory import Topology
from nexiqon_core.runner import load_factory

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "contracts" / "openapi"
SCHEMAS_OUT = ROOT / "contracts" / "schemas" / "config"


def config_schemas() -> dict[str, str]:
    from nexiqon_config import kinds

    return {
        f"{kind}.schema.json": json.dumps(kinds.schema(kind), indent=2) + "\n"
        for kind in kinds.KINDS
    }


def render(service: str) -> str:
    app = load_factory(service)()
    spec = app.openapi()
    spec["servers"] = [{"url": f"/{service}"}]
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    topology = Topology.load(ROOT / "deploy" / "groups.yaml")
    stale: list[str] = []
    for group in topology.groups.values():
        for service in group.services:
            target = OUT / f"{service}.json"
            content = render(service)
            if args.check:
                if not target.exists() or target.read_text(encoding="utf-8") != content:
                    stale.append(service)
            else:
                OUT.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
    for filename, content in config_schemas().items():
        target = SCHEMAS_OUT / filename
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                stale.append(f"schemas/config/{filename}")
        else:
            SCHEMAS_OUT.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    if stale:
        print("stale contracts (run `make contracts`):", ", ".join(stale))
        return 1
    print("contracts ok" if args.check else f"wrote contracts to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
