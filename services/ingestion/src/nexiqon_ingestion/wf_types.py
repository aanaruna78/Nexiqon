"""Plain data passed between workflows and activities (safe inside Temporal's sandbox)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ItemRef:
    uri: str
    title: str | None = None
    version: str | None = None
    media_type: str | None = None
    size: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Discovery:
    run_id: str
    items: list[ItemRef]


@dataclass
class FetchOutcome:
    document_id: str | None
    changed: bool
