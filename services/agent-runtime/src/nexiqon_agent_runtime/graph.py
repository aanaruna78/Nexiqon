"""Compile a validated GraphSpec into a LangGraph StateGraph bound to one run (AG-01)."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from nexiqon_agent_runtime.nodes import FACTORIES, WAITS, RunContext
from nexiqon_agent_runtime.spec import NODE_TYPES, GraphSpec, fallback_target
from nexiqon_agent_runtime.state import AgentState


def _outcome(state: AgentState) -> str:
    return str(state.get("outcome") or "")


def wait_id(node_id: str) -> str:
    return f"{node_id}__wait"


def compile_graph(spec: GraphSpec, run: RunContext, checkpointer: BaseCheckpointSaver[Any]) -> Any:
    # LangGraph's overloads do not accept plain async callables under strict mypy.
    graph: Any = StateGraph(AgentState)
    for n in spec.nodes:
        graph.add_node(n.id, FACTORIES[n.type](n, run))
        if n.type in WAITS:
            graph.add_node(wait_id(n.id), WAITS[n.type](n, run))
    graph.add_edge(START, spec.entry)
    fallback = fallback_target(spec)
    for n in spec.nodes:
        outcomes = NODE_TYPES[n.type]
        edges = {e.when: e.to for e in spec.edges if e.from_ == n.id}
        if n.type == "escalate":
            # Asks the user to confirm the handoff record when the pack's tool needs it.
            graph.add_conditional_edges(n.id, _outcome, {"ask": wait_id(n.id), "done": END})
            graph.add_edge(wait_id(n.id), END)
        elif outcomes == frozenset():
            graph.add_edge(n.id, END)
        elif outcomes is None:
            graph.add_edge(n.id, edges[None])
        else:
            # Outcomes the pack does not route go to the graph's safe exit (escalate or respond).
            full = {o: edges.get(o, fallback) for o in outcomes}
            if n.type == "clarify":
                graph.add_conditional_edges(
                    n.id, _outcome, {"ask": wait_id(n.id), "unresolved": full["unresolved"]}
                )
                graph.add_conditional_edges(wait_id(n.id), _outcome, {"answered": full["answered"]})
            elif n.type == "approve":
                graph.add_edge(n.id, wait_id(n.id))
                graph.add_conditional_edges(
                    wait_id(n.id),
                    _outcome,
                    {"approved": full["approved"], "declined": full["declined"]},
                )
            else:
                graph.add_conditional_edges(n.id, _outcome, full)
    return graph.compile(checkpointer=checkpointer)
