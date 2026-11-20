"""Nexiqon plugin SDK: connectors, parsers, chunkers and evaluators are plugins with a manifest.

A plugin package exposes objects (or zero-argument factories) under the ``nexiqon.plugins`` entry
point group; the ingestion service discovers them at start-up, so adding one needs no core change::

    [project.entry-points."nexiqon.plugins"]
    my-connector = "my_package.plugin:connector"   # an instance, or a function returning some

Evaluators use their own group, ``nexiqon.evaluators``, and are loaded by the evaluation service.
"""

from nexiqon_sdk.manifest import Manifest, PluginKind
from nexiqon_sdk.ports import Chunker, Connector, ConnectorContext, Evaluator, Parser
from nexiqon_sdk.registry import PluginError, Registry
from nexiqon_sdk.types import (
    Block,
    ChunkDraft,
    Content,
    EvalCase,
    EvalCitation,
    EvalObservation,
    Item,
    ParsedDocument,
    Score,
    estimate_tokens,
)

__all__ = [
    "Block",
    "ChunkDraft",
    "Chunker",
    "Connector",
    "ConnectorContext",
    "Content",
    "EvalCase",
    "EvalCitation",
    "EvalObservation",
    "Evaluator",
    "Item",
    "Manifest",
    "ParsedDocument",
    "Parser",
    "PluginError",
    "PluginKind",
    "Registry",
    "Score",
    "estimate_tokens",
]
