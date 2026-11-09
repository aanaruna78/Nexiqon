"""Graph validation (AG-01): bad graphs fail before anything runs, with every problem listed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from nexiqon_agent_runtime.spec import GraphError, fallback_target, validate_graph

PACK = yaml.safe_load(
    (Path(__file__).resolve().parents[3] / "packs/saas-knowledge-assistant/pack.yaml").read_text()
)
GRAPH: dict[str, Any] = PACK["spec"]["graph"]


def test_the_saas_pack_graph_is_valid() -> None:
    spec = validate_graph(GRAPH)
    assert spec.entry == "route"
    assert fallback_target(spec) == "escalate"


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda g: g.update(entry="nowhere"), "entry 'nowhere' is not a node"),
        (lambda g: g["nodes"].append({"id": "x", "type": "teleport"}), "unknown type 'teleport'"),
        (
            lambda g: g["edges"].append({"from": "respond", "to": "route"}),
            "ends the turn and cannot have outgoing edges",
        ),
        (
            lambda g: g["edges"].append({"from": "route", "to": "respond", "when": "banana"}),
            "unknown outcome 'banana'",
        ),
        (
            lambda g: g["edges"].append({"from": "route", "to": "escalate", "when": "knowledge"}),
            "outcome 'knowledge' has more than one edge",
        ),
        (
            lambda g: g["edges"].append({"from": "retrieve", "to": "respond"}),
            "needs exactly one unconditional outgoing edge",
        ),
        (
            lambda g: g["nodes"].append({"id": "orphan", "type": "respond"}),
            "'orphan' is unreachable",
        ),
        (
            lambda g: g["edges"].append({"from": "route", "to": "ghost", "when": "unclear"}),
            "unknown node 'ghost'",
        ),
        (lambda g: g["nodes"].append({"id": "Bad-Id", "type": "respond"}), "lowercase letters"),
    ],
)
def test_invalid_graphs_are_explained(change: Any, problem: str) -> None:
    import copy

    graph = copy.deepcopy(GRAPH)
    change(graph)
    with pytest.raises(GraphError) as info:
        validate_graph(graph)
    assert any(problem in p for p in info.value.problems), info.value.problems


def test_graph_without_an_exit_is_rejected() -> None:
    graph = {
        "entry": "a",
        "nodes": [{"id": "a", "type": "retrieve"}, {"id": "b", "type": "retrieve"}],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    }
    with pytest.raises(GraphError, match="no reachable node ends the turn"):
        validate_graph(graph)
