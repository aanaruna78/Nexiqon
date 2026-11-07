from pathlib import Path

import pytest

from nexiqon_core.settings import CONFIG_FILES_ENV, CoreSettings, deep_merge


def test_deep_merge_overrides_nested_keys_only() -> None:
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    assert deep_merge(base, {"nested": {"y": 3}}) == {"a": 1, "nested": {"x": 1, "y": 3}}
    assert base["nested"] == {"x": 1, "y": 2}  # input not mutated


def test_layers_then_env_then_kwargs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    platform = tmp_path / "platform.yaml"
    platform.write_text(
        "log_level: WARNING\ntelemetry:\n  enabled: true\n  otlp_endpoint: http://a\n"
    )
    tenant = tmp_path / "tenant.yaml"
    tenant.write_text("telemetry:\n  otlp_endpoint: http://b\n")
    monkeypatch.setenv(CONFIG_FILES_ENV, f"{platform},{tenant}")

    s = CoreSettings()
    assert s.log_level == "WARNING"
    assert s.telemetry.enabled is True
    assert s.telemetry.otlp_endpoint == "http://b"

    monkeypatch.setenv("NEXIQON_LOG_LEVEL", "DEBUG")
    assert CoreSettings().log_level == "DEBUG"
    assert CoreSettings(log_level="ERROR").log_level == "ERROR"


def test_layer_must_be_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just a list\n")
    monkeypatch.setenv(CONFIG_FILES_ENV, str(bad))
    with pytest.raises(ValueError, match="mapping"):
        CoreSettings()
