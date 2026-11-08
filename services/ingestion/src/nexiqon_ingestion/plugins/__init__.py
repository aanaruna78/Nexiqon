"""Built-in plugins, registered through the ``nexiqon.plugins`` entry point like any other."""

from __future__ import annotations

from typing import Any


def builtin() -> list[Any]:
    from nexiqon_ingestion.plugins.chunkers import CHUNKERS
    from nexiqon_ingestion.plugins.connectors import CONNECTORS
    from nexiqon_ingestion.plugins.parsers import PARSERS

    return [*CONNECTORS, *PARSERS, *CHUNKERS]
