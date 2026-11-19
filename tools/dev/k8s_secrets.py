"""Kubernetes Secrets the Helm chart expects, from the local development keys (evaluation only).

    uv run python tools/dev/gen_dev_secrets.py          # once: creates deploy/compose/config/dev-*.yaml
    uv run python tools/dev/k8s_secrets.py | kubectl -n nexiqon apply -f -

Production clusters get these Secrets from OpenBao or External Secrets, never from this script.
"""

from __future__ import annotations

import base64
import secrets
import sys
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[2] / "deploy" / "compose" / "config"
# Secret file name in the chart -> local development file.
KEY_FILES = {
    "secrets.yaml": "dev-secrets.yaml",
    "service-keys.yaml": "dev-service-keys.yaml",
    "identity-ingestion.yaml": "dev-secrets-ingestion.yaml",
    "identity-agent-runtime.yaml": "dev-secrets-agent-runtime.yaml",
    "identity-channel.yaml": "dev-secrets-channel.yaml",
    "identity-tool-gateway.yaml": "dev-secrets-tool-gateway.yaml",
    "identity-evaluation.yaml": "dev-secrets-evaluation.yaml",
    "identity-conversation.yaml": "dev-secrets-conversation.yaml",
    "identity-metering.yaml": "dev-secrets-metering.yaml",
    "identity-governance.yaml": "dev-secrets-governance.yaml",
}


def _secret(name: str, data: dict[str, str]) -> dict[str, object]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "labels": {"app.kubernetes.io/part-of": "nexiqon"}},
        "type": "Opaque",
        "data": {k: base64.b64encode(v.encode()).decode() for k, v in data.items()},
    }


def main() -> int:
    missing = [src for src in KEY_FILES.values() if not (CONFIG / src).exists()]
    if missing:
        sys.exit(f"missing {', '.join(missing)}: run tools/dev/gen_dev_secrets.py first")
    keys = {name: (CONFIG / src).read_text() for name, src in KEY_FILES.items()}
    studio = {"STUDIO_SESSION_SECRET": secrets.token_hex(32)}
    print(yaml.safe_dump_all([_secret("nexiqon-keys", keys), _secret("nexiqon-studio", studio)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
