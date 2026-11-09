# agent-runtime

Runs agents defined entirely by configuration. Plane: **data**; runs in the `agent` group.

`POST /v1/agents/{agent}/runs {thread_id, input | resume, history, locale}` runs one turn, or resumes
after a clarifying question or an approval. It returns `completed` (with the answer contract),
`interrupted` (what to ask the user) or `failed`.

1. The agent is resolved from config: merged settings, Domain Pack and graph. The pack graph (or
   `graph_override`) is **validated** (`POST /v1/graphs/validate` explains problems), then compiled to
   LangGraph.
2. The node library: `route` · `retrieve` · `call_tool` · `validate_evidence` · `clarify` · `approve`
   · `respond` · `escalate`. Intents, tools, prompts and thresholds all come from the pack and agent.
3. State is checkpointed per thread in this service's tenant-scoped tables. A restart resumes
   where the conversation left off, and another tenant cannot read it.
4. Every run is traced (`GET /v1/runs/{id}`, `GET /v1/threads/{id}/runs`): each node's outcome,
   timing and key facts, for the Answer Inspector.

Model, retrieval and tool calls use the **caller's** token. agent-runtime's own service identity
only reads agent configuration and collection names (ADR 0017, ADR 0018).
