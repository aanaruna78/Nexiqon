from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PluginKind(StrEnum):
    CONNECTOR = "connector"
    PARSER = "parser"
    CHUNKER = "chunker"


class Manifest(BaseModel):
    """What Studio shows in the gallery and how a plugin's configuration is validated."""

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    kind: PluginKind
    version: str = "1.0.0"
    title: str
    description: str = ""
    # JSON Schema (2020-12) for this plugin's configuration; Studio renders it as a form.
    config_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "additionalProperties": False, "properties": {}}
    )
    # Free-form capability flags, e.g. "discover", "push", "incremental", "schedule", "headings".
    capabilities: list[str] = Field(default_factory=list)
    # Parsers: media types and file extensions they handle.
    media_types: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)
    icon: str | None = None
