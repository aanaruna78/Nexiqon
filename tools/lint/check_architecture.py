"""Architecture rules enforced in CI (ARCHITECTURE.md §4, PLAN.md §6).

1. Vendor SDKs may only be imported inside an ``adapters`` package.
2. Core code (libs/, services/) must not contain domain vocabulary; domains live in packs/.

Exit code 1 lists every violation. Add a trailing ``# arch: allow`` to a line for a reviewed exception.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = [ROOT / "libs", ROOT / "services"]

# fmt: off
# Top-level modules of vendor SDKs that must stay behind ports.
VENDOR_MODULES = {
    "openai", "anthropic", "google", "vertexai", "boto3", "botocore", "aiobotocore", "azure",
    "nats", "temporalio", "redis", "valkey", "minio", "hvac", "clerk_backend_api", "auth0",
    "keycloak", "neo4j", "qdrant_client", "opensearchpy", "pymilvus", "langchain_openai",
    "langchain_anthropic", "ollama", "vllm", "cohere", "voyageai", "clamd", "digitalocean",
    "pydo",
}

# Domain words that belong in Domain Packs, not core code.
DOMAIN_WORDS = [
    "ticket", "subscription", "invoice", "refund", "warranty", "work_order", "workorder",
    "sku", "catalog", "shipment", "patient", "claim_number",
]
# fmt: on
# Letter boundaries (not \b) so snake_case names like create_ticket are caught.
DOMAIN_RE = re.compile(r"(?<![a-z])(" + "|".join(DOMAIN_WORDS) + r")s?(?![a-z])", re.IGNORECASE)
ALLOW = "# arch: allow"


def python_files() -> list[Path]:
    files: list[Path] = []
    for base in SCAN:
        files.extend(p for p in base.rglob("*.py") if ".venv" not in p.parts)
    return sorted(files)


def vendor_violations(path: Path, source: str) -> list[str]:
    if "adapters" in path.parts:
        return []
    lines = source.splitlines()
    problems: list[str] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            top = name.split(".")[0]
            if top in VENDOR_MODULES and ALLOW not in lines[node.lineno - 1]:
                problems.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: vendor SDK '{name}' imported "
                    "outside an adapters package"
                )
    return problems


def domain_violations(path: Path, source: str) -> list[str]:
    problems: list[str] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        if ALLOW in line:
            continue
        match = DOMAIN_RE.search(line)
        if match:
            problems.append(
                f"{path.relative_to(ROOT)}:{lineno}: domain word '{match.group(0)}' in core code "
                "(move it to a Domain Pack)"
            )
    return problems


def main() -> int:
    problems: list[str] = []
    for path in python_files():
        source = path.read_text(encoding="utf-8")
        problems += vendor_violations(path, source)
        problems += domain_violations(path, source)
    for p in problems:
        print(p)
    print(f"architecture check: {len(problems)} violation(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
