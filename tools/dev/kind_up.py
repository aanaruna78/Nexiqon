"""Install Nexiqon on a local kind cluster from the Helm chart (DV-02 acceptance: installs on kind).

Needs docker, kind, kubectl and helm on PATH.

    uv run python tools/dev/kind_up.py            # create cluster, build + load images, install
    uv run python tools/dev/kind_up.py --delete   # remove the cluster

Then: kubectl -n nexiqon port-forward svc/gateway 8000:8080 and open http://localhost:8000/gateway/healthz
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLUSTER = "nexiqon"
NAMESPACE = "nexiqon"
CHART = ROOT / "deploy" / "helm" / "nexiqon"


def run(*cmd: str, stdin: str | None = None) -> str:
    print("+", " ".join(cmd), flush=True)
    # Developer tool: fixed commands (docker, kind, kubectl, helm, uv), no user input.
    return subprocess.run(  # noqa: S603
        cmd, check=True, text=True, input=stdin, capture_output=stdin is not None
    ).stdout


def main() -> int:
    if "--delete" in sys.argv:
        run("kind", "delete", "cluster", "--name", CLUSTER)
        return 0
    clusters = subprocess.run(
        ["kind", "get", "clusters"],  # noqa: S607
        capture_output=True,
        text=True,
    ).stdout.split()
    if CLUSTER not in clusters:
        run("kind", "create", "cluster", "--name", CLUSTER, "--wait", "120s")
    run("docker", "build", "-t", "nexiqon/platform:dev", "-f", "deploy/docker/Dockerfile", ".")
    run(
        "docker",
        "build",
        "-t",
        "nexiqon/studio:dev",
        "-f",
        "deploy/docker/studio.Dockerfile",
        "frontend",
    )
    for image in ("nexiqon/platform:dev", "nexiqon/studio:dev"):
        run("kind", "load", "docker-image", image, "--name", CLUSTER)
    subprocess.run(["kubectl", "create", "namespace", NAMESPACE], capture_output=True)  # noqa: S603, S607
    run("uv", "run", "python", "tools/dev/gen_dev_secrets.py")
    manifest = run("uv", "run", "python", "tools/dev/k8s_secrets.py", stdin="")
    run("kubectl", "-n", NAMESPACE, "apply", "-f", "-", stdin=manifest)
    run(
        "helm",
        "upgrade",
        "--install",
        "nexiqon",
        str(CHART),
        "-n",
        NAMESPACE,
        "-f",
        str(CHART / "values" / "kind.yaml"),
        "--wait",
        "--timeout",
        "15m",
    )
    run("kubectl", "-n", NAMESPACE, "get", "pods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
