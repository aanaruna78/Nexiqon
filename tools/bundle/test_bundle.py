"""Install bundles (DV-05, DV-06) ship exactly what the single-node install runs."""

from __future__ import annotations

from pathlib import Path

import yaml

from tools.bundle.build_bundle import SINGLE, images, stage_files, write_checksums


def compose() -> dict[str, object]:
    data: dict[str, object] = yaml.safe_load((SINGLE / "compose.yaml").read_text())
    return data


def test_every_image_is_pinned_and_the_platform_uses_the_bundle_version() -> None:
    refs = images(compose(), "9.9.9", gpu=True)
    assert "nexiqon/platform:9.9.9" in refs
    assert "nexiqon/studio:9.9.9" in refs
    assert any(r.startswith("vllm/vllm-openai:") for r in refs)
    for ref in refs:
        name, _, tag = ref.rpartition(":")
        assert name, ref
        assert tag not in ("", "latest"), ref


def test_gpu_images_are_left_out_unless_asked_for() -> None:
    assert not any("vllm" in r for r in images(compose(), "1.0.0", gpu=False))


def test_the_bundle_has_no_install_time_secrets_and_checksums_cover_every_file(
    tmp_path: Path,
) -> None:
    stage_files(tmp_path, "1.0.0")
    single = tmp_path / "deploy" / "single-node"
    assert (single / "install.sh").exists()
    assert (single / "gateway" / "envoy.yaml").exists()
    assert not (single / ".env").exists()
    assert not (single / "config").exists()
    # compose mounts the chart's policies and flags by relative path
    assert (tmp_path / "deploy/helm/nexiqon/files/policies/authz.rego").exists()
    write_checksums(tmp_path)
    listed = {line.split("  ", 1)[1] for line in (tmp_path / "SHA256SUMS").read_text().splitlines()}
    files = {
        p.relative_to(tmp_path).as_posix()
        for p in tmp_path.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS"
    }
    assert listed == files
