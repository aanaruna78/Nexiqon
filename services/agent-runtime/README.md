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

## Streaming, escalation and guards (ADR 0020)

`POST /v1/agents/{agent}/runs/stream` runs the same turn as server-sent events:
`run` → `status` → `sources` → `tool` → `delta` (answer text as it is written) → `result` (the
RunOut). The streamed text is provisional; `result.answer` holds the checked text and citations.
Refusals (unknown agent, someone else's thread, a pending approval) are plain HTTP errors. A turn
finishes and is recorded even if the caller disconnects.

**Escalation** follows the pack's `escalation` rules:

- `after_failed_turns` counts turns without a grounded answer, across turns.
- `on_low_evidence: false` answers "unavailable" instead of handing over.
- `handoff_tool` records the handoff through tool-gateway. If that tool needs confirmation, the
  user confirms first (`interrupt.purpose == "handoff"`).

`handoff: true` on a run (the widget's "talk to a person" button) skips intent routing.

**Guards** (`guards.py`):

- blocked topics get a fixed refusal before any model call;
- instruction-like lines in sources are replaced before the model sees them;
- images, links to anything but cited sources, and raw HTML are removed from answers;
- an answer that repeats the system prompt is withheld.

The pack's red-team set (`eval/redteam.yaml`) runs in `tests/test_streaming.py` against a model
that obeys every injected instruction.

