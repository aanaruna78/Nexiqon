"""GitOps for Domain Packs: import every packs/*/pack.yaml into a tenant through the gateway.

    uv run python -m tools.packs.apply --tenant acme --token "$IDP_TOKEN" [--publish] [--deploy dev]

Each pack is validated locally first (same schema as the config service), then imported as a new
draft (or created). With --publish the draft is published; with --deploy it is deployed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from nexiqon_config.kinds import validate
from nexiqon_config.packs import parse_pack

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gateway", default="http://localhost:8000")
    parser.add_argument("--tenant", required=True, help="tenant slug or id")
    parser.add_argument("--token", required=True, help="IdP access token or nxq_ API key")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--deploy", choices=["dev", "staging", "prod"])
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    files = sorted((ROOT / "packs").glob("*/pack.yaml"))
    failed = False
    for path in files:
        name, spec = parse_pack(path.read_text())
        problems = validate("domain_pack", spec)
        print(f"{'OK  ' if not problems else 'FAIL'} {name} ({path.relative_to(ROOT)})")
        for p in problems:
            print(f"     {p.path or '<root>'}: {p.message}")
        failed |= bool(problems)
    if failed or args.validate_only:
        return 1 if failed else 0

    headers = {"Authorization": f"Bearer {args.token}", "X-Nexiqon-Tenant": args.tenant}
    with httpx.Client(base_url=f"{args.gateway}/config", headers=headers, timeout=30) as api:
        for path in files:
            r = api.post(
                "/v1/packs/import",
                content=path.read_text(),
                headers={"content-type": "application/yaml"},
            )
            r.raise_for_status()
            name, version = parse_pack(path.read_text())[0], r.json()["version"]
            print(f"imported {name} as version {version}")
            if args.publish or args.deploy:
                api.post(
                    f"/v1/objects/domain_pack/{name}/versions/{version}/publish"
                ).raise_for_status()
                print(f"published {name} v{version}")
            if args.deploy:
                api.put(
                    f"/v1/objects/domain_pack/{name}/deployments/{args.deploy}",
                    json={"version": version},
                ).raise_for_status()
                print(f"deployed {name} v{version} to {args.deploy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
