"""Vendor tool: create the licence signing key, and issue licences (DV-06).

    # once: the vendor key pair. Keep the private key offline (a vault or hardware key).
    uv run python tools/licence/issue.py keygen --out vendor-licence-2026.pem --kid vendor-2026

    # per customer: a licence file, valid offline
    uv run python tools/licence/issue.py issue --key vendor-licence-2026.pem --kid vendor-2026 \\
        --customer "Example Co" --expires 2027-12-31 --max-tenants 5 --deployment air-gapped \\
        > example-co.licence

The public key printed by keygen goes into the installation's settings
(licence.public_keys.<kid>), which the bundle ships; the private key never leaves the vendor.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from nexiqon_core.keys import keypair
from nexiqon_core.licence import Licence, issue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen", help="create the vendor licence key pair")
    k.add_argument("--out", type=Path, required=True)
    k.add_argument("--kid", required=True)
    i = sub.add_parser("issue", help="issue a licence")
    i.add_argument("--key", type=Path, required=True)
    i.add_argument("--kid", required=True)
    i.add_argument("--customer", required=True)
    i.add_argument("--expires", type=date.fromisoformat, required=True)
    i.add_argument("--grace-days", type=int, default=30)
    i.add_argument("--max-tenants", type=int, default=None)
    i.add_argument(
        "--deployment", choices=["private", "air-gapped", "hybrid", "any"], default="any"
    )
    i.add_argument("--feature", action="append", default=[])
    args = parser.parse_args(argv)

    if args.cmd == "keygen":
        if args.out.exists():
            print(f"{args.out} exists; refusing to overwrite a signing key", file=sys.stderr)
            return 1
        private, public = keypair()
        args.out.write_text(private)
        args.out.chmod(0o600)
        print(f"# private key: {args.out} (keep offline)", file=sys.stderr)
        print(yaml.safe_dump({"licence": {"public_keys": {args.kid: public}}}))
        return 0

    licence = Licence(
        id=f"lic-{uuid.uuid4().hex[:12]}",
        customer=args.customer,
        issued=datetime.now(UTC).date(),
        expires=args.expires,
        grace_days=args.grace_days,
        max_tenants=args.max_tenants,
        deployment=args.deployment,
        features=args.feature,
    )
    print(issue(licence, args.key.read_text(), args.kid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
