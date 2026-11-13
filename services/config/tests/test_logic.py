"""Pure configuration logic: schemas, graph checks, layering, floors, diff, pack files."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from nexiqon_config import kinds
from nexiqon_config.diff import diff
from nexiqon_config.packs import parse_pack, render_pack
from nexiqon_config.resolution import FloorRule, Layer, check_floors, merge_layers
from nexiqon_config.store import platform_floors

ROOT = Path(__file__).resolve().parents[3]
PACKS = sorted((ROOT / "packs").glob("*/pack.yaml"))


@pytest.mark.parametrize("kind", kinds.KINDS)
def test_every_schema_is_a_valid_2020_12_schema(kind: str) -> None:
    Draft202012Validator.check_schema(kinds.schema(kind))


@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.parent.name)
def test_repo_packs_are_valid_and_round_trip(path: Path) -> None:
    name, spec = parse_pack(path.read_text())
    assert kinds.validate("domain_pack", spec) == []
    assert parse_pack(render_pack(name, spec)) == (name, spec)


def _pack() -> dict[str, Any]:
    return parse_pack((ROOT / "packs/saas-knowledge-assistant/pack.yaml").read_text())[1]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["graph"].update(entry="nope"), "entry node 'nope' is not defined"),
        (
            lambda p: p["graph"]["edges"].append({"from": "route", "to": "ghost"}),
            "unknown node 'ghost'",
        ),
        (
            lambda p: p["graph"]["nodes"].append({"id": "orphan", "type": "respond"}),
            "unreachable from entry",
        ),
        (lambda p: p["intents"].append(dict(p["intents"][0])), "intent names must be unique"),
        (lambda p: p["graph"]["nodes"][0].update(type="shell_exec"), "is not one of"),
        (lambda p: p.update(surprise=1), "Additional properties are not allowed"),
    ],
)
def test_pack_semantic_and_schema_errors(mutate: Any, message: str) -> None:
    pack = _pack()
    mutate(pack)
    problems = kinds.validate("domain_pack", pack)
    assert any(message in p.message for p in problems), problems


def test_tool_schema_rejects_raw_secrets_and_bad_credential_refs() -> None:
    tool = {
        "description": "Look up an account",
        "kind": "rest",
        "risk_level": "read",
        "input_schema": {"type": "object"},
        "request": {
            "method": "GET",
            "url_template": "https://api.example.com/a/{id}",
            "host_allowlist": ["api.example.com"],
        },
    }
    assert kinds.validate("tool", tool) == []
    leaky = copy.deepcopy(tool)
    leaky["request"]["headers"] = {"Authorization": "Bearer sk-live-123"}
    assert kinds.validate("tool", leaky)
    # Plain http passes the schema; tool-gateway refuses it outside development (allow_insecure_http).
    insecure = copy.deepcopy(tool)
    insecure["request"]["url_template"] = "http://api.example.com/a"
    assert kinds.validate("tool", insecure) == []
    assert kinds.validate("tool", {**tool, "credential_ref": "plaintext-password"})
    assert kinds.validate("tool", {**tool, "credential_ref": "secret://../other-tenant"})
    no_allowlist = copy.deepcopy(tool)
    del no_allowlist["request"]["host_allowlist"]
    assert kinds.validate("tool", no_allowlist)


def test_merge_layers_with_provenance() -> None:
    resolved = merge_layers(
        [
            Layer(
                "platform",
                {"guardrails": {"pii_redaction": True, "max_answer_tokens": 900}, "tags": ["a"]},
            ),
            Layer("pack", {"guardrails": {"max_answer_tokens": 700}}),
            Layer("agent", {"tags": ["b"], "behaviour": {"tone": "formal"}}),
            Layer("env", {"guardrails": {"max_answer_tokens": 500}}),
        ]
    )
    assert resolved.values == {
        "guardrails": {"pii_redaction": True, "max_answer_tokens": 500},
        "tags": ["b"],
        "behaviour": {"tone": "formal"},
    }
    assert resolved.provenance == {
        "guardrails.pii_redaction": "platform",
        "guardrails.max_answer_tokens": "env",
        "tags": "agent",
        "behaviour.tone": "agent",
    }


def test_layers_do_not_alias_inputs() -> None:
    base = {"x": {"y": [1]}}
    resolved = merge_layers([Layer("a", base)])
    resolved.values["x"]["y"].append(2)
    assert base == {"x": {"y": [1]}}


@pytest.mark.parametrize(
    ("op", "value", "actual", "ok"),
    [
        ("equals", True, True, True),
        ("equals", True, False, False),
        ("subset_of", ["openai_compatible"], "openai_compatible", True),
        ("subset_of", ["openai_compatible"], "openai", False),
        ("subset_of", ["a", "b"], ["a"], True),
        ("subset_of", ["a", "b"], ["a", "c"], False),
        ("min", 0.5, 0.6, True),
        ("min", 0.5, 0.4, False),
        ("max", 365, 400, False),
        ("max", 365, "lots", False),
    ],
)
def test_floor_operators(op: str, value: Any, actual: Any, ok: bool) -> None:
    rule = FloorRule("a.b", op, value, "test")
    assert (check_floors({"a": {"b": actual}}, [rule]) == []) is ok


def test_missing_value_fails_closed() -> None:
    violations = check_floors(
        {}, [FloorRule("guardrails.pii_redaction", "equals", True, "platform")]
    )
    assert violations
    assert "platform" in violations[0].message


def test_platform_floors_cover_design_invariants() -> None:
    paths = {r.path for r in platform_floors()}
    assert {
        "guardrails.pii_redaction",
        "tools_policy.write_confirmation",
        "model.data_policy.allow_training",
    } <= paths


def test_diff() -> None:
    ops = diff({"a": 1, "b": {"c": 2, "d": 3}}, {"a": 1, "b": {"c": 4}, "e": 5})
    assert ops == [
        {"op": "replace", "path": "b.c", "old": 2, "new": 4},
        {"op": "remove", "path": "b.d", "old": 3},
        {"op": "add", "path": "e", "new": 5},
    ]
