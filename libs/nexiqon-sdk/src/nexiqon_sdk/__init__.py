"""Nexiqon plugin SDK: connectors, parsers and chunkers are plugins with a manifest.

A plugin package exposes objects (or zero-argument factories) under the ``nexiqon.plugins`` entry
point group; the ingestion service discovers them at start-up, so adding one needs no core change::

    [project.entry-points."nexiqon.plugins"]
    my-connector = "my_package.plugin:MyConnector"
"""

from nexiqon_sdk.manifest import Manifest, PluginKind
from nexiqon_sdk.ports import Chunker, Connector, ConnectorContext, Parser
from nexiqon_sdk.registry import PluginError, Registry
from nexiqon_sdk.types import Block, ChunkDraft, Content, Item, ParsedDocument, estimate_tokens

__all__ = [
    "Block",
    "ChunkDraft",
    "Chunker",
    "Connector",
    "ConnectorContext",
    "Content",
    "Item",
    "Manifest",
    "ParsedDocument",
    "Parser",
    "PluginError",
    "PluginKind",
    "Registry",
    "estimate_tokens",
]
