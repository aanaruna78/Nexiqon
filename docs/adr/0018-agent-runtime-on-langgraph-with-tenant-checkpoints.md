# ADR 0018: Agent runtime on LangGraph with tenant-scoped checkpoints

Status: Accepted (2026-11-09)

## Decision

- **Graphs come only from configuration.** A Domain Pack's `graph` (or an agent's `graph_override`) is
  validated before anything runs: known node types, edges whose outcomes match each node's
  outcomes, a single unconditional edge where required, reachability, and a reachable exit. It is
  then compiled into a LangGraph `StateGraph` for each run. Outcomes the pack does not route go to
  the graph's safe exit (escalate, else respond). A recursion limit stops loops.
- **Node library** (no domain words): `route` (pack intents; examples first, then the model with
  structured output; capability-aware through the model gateway), `retrieve`, `call_tool` (tool port;
  the tool gateway arrives in slice 2), `validate_evidence`, `clarify`, `approve`, `respond` (verified
  citations, labelled with the strictest source classification), `escalate` (handoff summary).
- **Interrupts without repeated work.** `clarify` and `approve` each compile to an *ask* node and a
  *wait* node that holds `interrupt()`. A resume re-enters only the wait node, so the clarifying
  question or approval text is never regenerated.
- **Tenant-scoped checkpointer.** LangGraph's Postgres saver uses its own driver and tables without
  row-level security. We implement the saver contract on our RLS-forced tables (`agent_runtime.*`),
  bound to one tenant context per run. Thread ids are unique per tenant, and a thread belongs to the
  actor who started it.
- **Tokens never enter state.** Model, retrieval and tool calls use the caller's token, held only
  in the run's closure. Checkpoints contain plain JSON values. agent-runtime's own identity (ADR 0017)
  only reads agent configuration and collection names.
- **Conversation service** owns sessions, messages, the answer contract, feedback and retention
  (`retain_until` from the agent's retention profile, deleted by a sweep that a narrow RLS policy
  limits to expired rows).
- LangSmith tracing is switched off in-process; traces stay in our run records and OpenTelemetry.

## Why

Configuration-only graphs keep the core domain-agnostic and make packs portable. Validation up
front turns pack mistakes into editor errors rather than live failures. Our own checkpointer keeps
conversation state under the same tenant isolation as everything else.

## Consequences

- The saver tracks LangGraph's checkpoint contract (pinned 1.2.x). Upgrades run the checkpoint
  tests, including restart-resume and cross-tenant reads.
- Streaming (CH-01) and tool calls (T-01) plug into this runtime in the next slices.
