"""Layered settings.

Resolution order (later wins): defaults -> YAML layers listed in ``NEXIQON_CONFIG_FILES``
(comma separated, e.g. ``platform.yaml,deployment.yaml,region.yaml``) -> environment variables
(``NEXIQON_`` prefix, ``__`` for nesting) -> explicit init kwargs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

CONFIG_FILES_ENV = "NEXIQON_CONFIG_FILES"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict where ``override`` is merged recursively into ``base``."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_yaml_layers(paths: list[Path]) -> dict[str, Any]:
    """Load and deep-merge YAML files in order. Missing files are an error."""
    result: dict[str, Any] = {}
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"settings layer {path} must contain a mapping")
        result = deep_merge(result, data)
    return result


class YamlLayersSource(PydanticBaseSettingsSource):
    """Settings source reading the YAML layers named in ``NEXIQON_CONFIG_FILES``."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        raw = os.environ.get(CONFIG_FILES_ENV, "")
        paths = [Path(p.strip()) for p in raw.split(",") if p.strip()]
        self._data = load_yaml_layers(paths)

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return {k: v for k, v in self._data.items() if k in self.settings_cls.model_fields}


class ContextTokenSettings(BaseModel):
    """Verification settings for the internal tenant-context token."""

    issuer: str = "nexiqon-identity"
    audience: str = "nexiqon-services"
    algorithm: Literal["ES256", "EdDSA", "RS256"] = "ES256"
    # PEM-encoded public keys by key id. Private keys live only in the identity service.
    public_keys: dict[str, str] = Field(default_factory=dict)
    leeway_seconds: int = 5


class TelemetrySettings(BaseModel):
    enabled: bool = False
    otlp_endpoint: str | None = None  # e.g. http://otel-collector:4318


class CoreSettings(BaseSettings):
    """Settings every service has. Services subclass this to add their own fields."""

    model_config = SettingsConfigDict(
        env_prefix="NEXIQON_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: str = "unknown"
    environment: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    database_url: SecretStr | None = None
    groups_file: Path = Path("deploy/groups.yaml")
    context_token: ContextTokenSettings = Field(default_factory=ContextTokenSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # First source has highest priority.
        return (
            init_settings,
            env_settings,
            file_secret_settings,
            YamlLayersSource(settings_cls),
        )
