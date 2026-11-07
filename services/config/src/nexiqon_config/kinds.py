"""Configuration kinds: JSON Schemas (package data, exported to contracts/schemas) + semantic checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

KINDS = (
    "domain_pack",
    "agent",
    "model_profile",
    "retrieval_profile",
    "tool",
    "channel",
    "tenant_settings",
    "security_floors",
    "retention_profile",
)


@dataclass(frozen=True)
class Problem:
    path: str  # dotted path inside the spec ("" = root)
    message: str


@cache
def schema(kind: str) -> dict[str, Any]:
    if kind not in KINDS:
        raise KeyError(kind)
    text = resources.files("nexiqon_config.schemas").joinpath(f"{kind}.schema.json").read_text()
    data: dict[str, Any] = json.loads(text)
    return data


@cache
def _validator(kind: str) -> Draft202012Validator:
    return Draft202012Validator(schema(kind))


def _dotted(parts: Any) -> str:
    return ".".join(str(p) for p in parts)


def validate(kind: str, spec: Any) -> list[Problem]:
    """Schema errors first; semantic checks only when the shape is valid."""
    errors = sorted(_validator(kind).iter_errors(spec), key=lambda e: list(e.absolute_path))
    problems = [Problem(_dotted(e.absolute_path), e.message) for e in errors]
    if problems:
        return problems
    if kind == "domain_pack":
        problems += validate_graph(spec["graph"], "graph")
        intents = {i["name"] for i in spec["intents"]}
        if len(intents) != len(spec["intents"]):
            problems.append(Problem("intents", "intent names must be unique"))
    if kind == "agent" and "graph_override" in spec:
        problems += validate_graph(spec["graph_override"], "graph_override")
    return problems


def validate_graph(graph: dict[str, Any], at: str) -> list[Problem]:
    problems: list[Problem] = []
    ids = [n["id"] for n in graph["nodes"]]
    known = set(ids)
    if len(known) != len(ids):
        problems.append(Problem(f"{at}.nodes", "node ids must be unique"))
    if graph["entry"] not in known:
        problems.append(Problem(f"{at}.entry", f"entry node {graph['entry']!r} is not defined"))
    for i, edge in enumerate(graph["edges"]):
        for end in ("from", "to"):
            if edge[end] not in known:
                problems.append(Problem(f"{at}.edges.{i}.{end}", f"unknown node {edge[end]!r}"))
    # Every node must be reachable from the entry, and a terminal node must exist.
    reachable, frontier = {graph["entry"]}, [graph["entry"]]
    while frontier:
        node = frontier.pop()
        for edge in graph["edges"]:
            if edge["from"] == node and edge["to"] not in reachable:
                reachable.add(edge["to"])
                frontier.append(edge["to"])
    unreachable = sorted(known - reachable)
    if unreachable and not problems:
        problems.append(Problem(f"{at}.nodes", f"unreachable from entry: {unreachable}"))
    terminals = {n["id"] for n in graph["nodes"] if n["type"] in ("respond", "escalate")}
    if not terminals:
        problems.append(Problem(f"{at}.nodes", "graph needs at least one respond or escalate node"))
    return problems
