"""Declarative graph specification (from a Domain Pack or an agent's ``graph_override``) and its
validation (AG-01). Validation runs before anything executes, so a bad graph fails at publish or
load time with every problem listed, never half-way through a conversation."""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from pydantic import BaseModel, Field

NODE_ID = re.compile(r"^[a-z][a-z0-9_]{0,40}$")

#: Node types in the library and the outcomes they can produce. ``None``: a single unconditional
#: edge. Empty set: terminal (the turn ends there).
NODE_TYPES: dict[str, frozenset[str] | None] = {
    "route": frozenset(
        {"knowledge", "action_read", "action_write", "handoff", "smalltalk", "unclear"}
    ),
    "retrieve": None,
    "call_tool": None,
    "validate_evidence": frozenset({"sufficient", "insufficient"}),
    "clarify": frozenset({"answered", "unresolved"}),
    "approve": frozenset({"approved", "declined"}),
    "respond": frozenset(),
    "escalate": frozenset(),
}
TERMINAL = {name for name, outcomes in NODE_TYPES.items() if outcomes == frozenset()}


class NodeSpec(BaseModel):
    id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeSpec(BaseModel):
    from_: str = Field(alias="from")
    to: str
    when: str | None = None

    model_config = {"populate_by_name": True}


class GraphSpec(BaseModel):
    entry: str
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]

    def node(self, node_id: str) -> NodeSpec:
        return next(n for n in self.nodes if n.id == node_id)


class GraphError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def validate_graph(raw: dict[str, Any]) -> GraphSpec:
    """Parse and check a graph; raises GraphError listing every problem found."""
    try:
        spec = GraphSpec.model_validate(raw)
    except ValueError as exc:
        raise GraphError([f"graph is malformed: {exc}"]) from exc
    problems: list[str] = []
    ids = [n.id for n in spec.nodes]
    for node_id in ids:
        if not NODE_ID.match(node_id):
            problems.append(
                f"node id {node_id!r} must be lowercase letters, digits and underscores"
            )
    duplicates = {i for i in ids if ids.count(i) > 1}
    problems += [f"node {d!r} is defined more than once" for d in sorted(duplicates)]
    for n in spec.nodes:
        if n.type not in NODE_TYPES:
            problems.append(f"node {n.id!r} has unknown type {n.type!r}")
    if spec.entry not in ids:
        problems.append(f"entry {spec.entry!r} is not a node")
    known = set(ids)
    outgoing: dict[str, list[EdgeSpec]] = {i: [] for i in ids}
    for e in spec.edges:
        if e.from_ not in known:
            problems.append(f"edge from unknown node {e.from_!r}")
            continue
        if e.to not in known:
            problems.append(f"edge {e.from_!r} -> unknown node {e.to!r}")
            continue
        outgoing[e.from_].append(e)
    for n in spec.nodes:
        outcomes = NODE_TYPES.get(n.type)
        edges = outgoing.get(n.id, [])
        if n.type not in NODE_TYPES:
            continue
        if outcomes == frozenset():
            if edges:
                problems.append(
                    f"{n.type} node {n.id!r} ends the turn and cannot have outgoing edges"
                )
        elif outcomes is None:
            if len(edges) != 1 or edges[0].when is not None:
                problems.append(
                    f"{n.type} node {n.id!r} needs exactly one unconditional outgoing edge"
                )
        else:
            whens = [e.when for e in edges]
            if not edges:
                problems.append(f"{n.type} node {n.id!r} has no outgoing edges")
            for w in whens:
                if w not in outcomes:
                    problems.append(
                        f"{n.type} node {n.id!r}: unknown outcome {w!r} (one of {sorted(outcomes)})"
                    )
            for w in {w for w in whens if whens.count(w) > 1}:
                problems.append(f"{n.type} node {n.id!r}: outcome {w!r} has more than one edge")
    if spec.entry in known:
        seen = {spec.entry}
        queue = deque([spec.entry])
        while queue:
            for e in outgoing.get(queue.popleft(), []):
                if e.to not in seen:
                    seen.add(e.to)
                    queue.append(e.to)
        problems += [f"node {i!r} is unreachable from {spec.entry!r}" for i in ids if i not in seen]
        if not any(spec.node(i).type in TERMINAL for i in seen if i in known):
            problems.append("no reachable node ends the turn (respond or escalate)")
    if problems:
        raise GraphError(problems)
    return spec


def fallback_target(spec: GraphSpec) -> str:
    """Where an outcome without an edge goes: escalate if the graph has one, else respond."""
    for wanted in ("escalate", "respond"):
        for n in spec.nodes:
            if n.type == wanted:
                return n.id
    raise GraphError(["graph has no respond or escalate node"])
