"""Build an install bundle (DV-05, DV-06): everything a server needs, in one archive.

    # connected single-node install: files only (images pulled at install time)
    uv run python -m tools.bundle.build_bundle --version 1.4.0

    # air-gapped: + every image (docker save), the chart, and model weights for --gpu installs
    uv run python -m tools.bundle.build_bundle --version 1.4.0 --airgap --gpu \\
        --models ~/.cache/huggingface --licence-keys vendor-licence-public.yaml --licence-required

Layout of nexiqon-<version>[-airgap].tar.gz:
    VERSION, SHA256SUMS (every file), README.md
    deploy/single-node/       compose file, install.sh, backup.sh, bootstrap scripts, gateway
    deploy/helm/nexiqon/      the Helm chart (Kubernetes installs; also the policies and flags)
    images/*.tar              --airgap: every image the install runs
    models/                   --airgap --gpu: Hugging Face cache with the vLLM models' weights
    licence-public-keys.yaml  the vendor keys that verify licences; LICENCE_REQUIRED if required

install.sh --offline checks SHA256SUMS, loads the images and copies the weights; it never pulls.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SINGLE = ROOT / "deploy" / "single-node"
CHART = ROOT / "deploy" / "helm" / "nexiqon"
GENERATED = {".env", "config", "tls", "backups"}  # install-time files, never shipped


def images(compose: dict[str, object], version: str, *, gpu: bool) -> list[str]:
    """Every image the single-node compose file runs, with variables resolved."""
    found: set[str] = set()
    services = compose.get("services", {})
    assert isinstance(services, dict)
    for svc in services.values():
        if not gpu and "gpu" in (svc.get("profiles") or []):
            continue
        image = str(svc["image"])
        image = re.sub(r"\$\{NEXIQON_VERSION[^}]*\}", version, image)
        image = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", image)
        if "$" in image:
            raise ValueError(f"unresolved variable in image {image!r}")
        found.add(image)
    return sorted(found)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(stage: Path) -> None:
    lines = [
        f"{sha256(p)}  {p.relative_to(stage).as_posix()}"
        for p in sorted(stage.rglob("*"))
        if p.is_file() and p.name != "SHA256SUMS"
    ]
    (stage / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def stage_files(stage: Path, version: str) -> None:
    (stage / "VERSION").write_text(version + "\n")
    shutil.copytree(
        SINGLE,
        stage / "deploy" / "single-node",
        ignore=lambda _d, names: [n for n in names if n in GENERATED],
    )
    shutil.copytree(CHART, stage / "deploy" / "helm" / "nexiqon")
    shutil.copy(SINGLE / "README.md", stage / "README.md")


def save_images(stage: Path, refs: list[str]) -> None:
    out = stage / "images"
    out.mkdir()
    for ref in refs:
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", ref)
        print(f"  saving {ref}", flush=True)
        subprocess.run(["docker", "image", "inspect", ref], check=True, capture_output=True)
        subprocess.run(["docker", "save", "-o", str(out / f"{name}.tar"), ref], check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--airgap", action="store_true", help="include every image")
    parser.add_argument("--gpu", action="store_true", help="include the vLLM images and weights")
    parser.add_argument("--models", type=Path, help="Hugging Face cache with the weights")
    parser.add_argument("--licence-keys", type=Path, help="vendor licence public keys (YAML)")
    parser.add_argument("--licence-required", action="store_true")
    args = parser.parse_args(argv)
    if args.licence_required and not args.licence_keys:
        parser.error("--licence-required needs --licence-keys")
    if args.airgap and args.gpu and not args.models:
        parser.error("--airgap --gpu needs --models (the weights cannot be downloaded offline)")

    name = f"nexiqon-{args.version}{'-airgap' if args.airgap else ''}"
    stage = args.out / name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    print(f"Building {name}")
    stage_files(stage, args.version)
    if args.licence_keys:
        shutil.copy(args.licence_keys, stage / "licence-public-keys.yaml")
    if args.licence_required:
        (stage / "LICENCE_REQUIRED").write_text("This installation needs a licence.\n")
    if args.airgap:
        compose = yaml.safe_load((SINGLE / "compose.yaml").read_text())
        save_images(stage, images(compose, args.version, gpu=args.gpu))
        if args.gpu:
            print(f"  copying model weights from {args.models}")
            shutil.copytree(args.models, stage / "models")
    write_checksums(stage)
    archive = args.out / f"{name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stage, arcname=name)
    shutil.rmtree(stage)
    print(f"Wrote {archive} ({archive.stat().st_size / 1e9:.2f} GB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
