"""The single-node bundle's gateway configuration, generated from the Helm chart so both installs
route, authorise and harden requests the same way (DV-05).

    docker run --rm -v $PWD/deploy/helm/nexiqon:/chart -w /chart alpine/helm:3.19.0 \\
        template nexiqon . --set gateway.hsts=true --set studio.enabled=false \\
      | python3 tools/bundle/single_node_gateway.py > deploy/single-node/gateway/envoy.yaml

CI renders it again and fails if the committed file differs.
"""

from __future__ import annotations

import sys

import yaml

HEADER = (
    "# Generated from the Helm chart by tools/bundle/single_node_gateway.py. Do not edit:\n"
    "# change the chart and generate again (CI checks the two agree).\n"
)


def extract(manifests: str) -> str:
    for doc in yaml.safe_load_all(manifests):
        if doc and doc.get("kind") == "ConfigMap" and doc["metadata"]["name"] == "nexiqon-gateway":
            return HEADER + str(doc["data"]["envoy.yaml"])
    raise SystemExit("no nexiqon-gateway ConfigMap in the rendered chart")


if __name__ == "__main__":
    sys.stdout.write(extract(sys.stdin.read()))
