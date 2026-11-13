# ADR 0020: Streaming, channels, escalation and prompt-injection defences

Status: Accepted (2026-11-13)

## Decision

- **Server-sent events, end to end.** Answers stream over SSE, which plain `fetch` can read through
  any proxy:
  - model-gateway: `POST /v1/chat/stream`;
  - agent-runtime: `POST /v1/agents/{agent}/runs/stream`;
  - conversation: `POST /v1/conversations/{id}/messages/stream`.

  Each layer runs the same checks as its non-streaming twin. Routing, floors, budgets, ownership
  and pending approvals are all checked **before** the first byte, so a refusal is an ordinary HTTP
  error, not a broken stream.
- **Events:**
  - `run`;
  - `status` (understanding, searching, writing, handing_over);
  - `sources` (citation, title, link);
  - `tool` (name, running, ok or failed);
  - `delta` (answer text);
  - then `result` from agent-runtime, which conversation stores and relays as `message`.

  The streamed text is provisional. The final message carries the answer after the output guard
  and citation verification, and it replaces the streamed text. Clients render text, never HTML.
- **Model streaming in adapters.** OpenAI-compatible, Anthropic and Gemini adapters parse their
  providers' SSE.
  - The gateway falls back to the next provider only before the first piece of text.
  - It holds back text after an unclosed `[`, so redaction placeholders are restored even when
    they are split across chunks.
  - Usage and cost are recorded when the stream ends.
  - Tool calls and JSON-schema output stay on the non-streaming endpoint.
- **A turn outlives its client.** agent-runtime and conversation run the turn in a task. If the
  browser disconnects, the turn still finishes and is stored.
- **Channels are a port.** The channel service has a registry of channel adapters: `widget` and
  `api` now; Slack, Teams and email later. Each turns a resolved agent into what that client
  needs. For the widget, that is title, greeting, starter questions and theme colour from the
  pack's `channels.widget`, plus the endpoints.
  - Channel reads agents with its **own** identity, `service:channel` (`config.agent.read` only).
    In the grouped topology it shares a process with agent-runtime, so its key lives under
    `channel_identity`.
  - The full agent configuration never leaves the platform.
- **Widget identity.** A widget key works only from its allowed origins, and every visitor needs a
  random `X-Nexiqon-Visitor` id. Identity issues the actor `widget:<key>:<visitor>`, so visitors
  never share conversations. Envoy answers CORS preflights for `/conversation` and `/channel`
  before ext_authz runs; identity still enforces the key's origins.
- **Escalation from the pack (CV-02).** The rules live in `escalation`:
  - `after_failed_turns` counts consecutive turns without a grounded answer. The count is kept
    in the checkpointed state across turns and reset by an answer or a handoff. Reaching it skips
    the clarifying question and escalates.
  - `on_low_evidence: false` gives an "unavailable" answer instead of a handoff.
  - `handoff_tool` names the tool that records the handoff. Its arguments come from the summary
    by field role (summary or description, subject or title), never from a model's guess. If the
    tool needs confirmation, the `escalate` node asks the user ("send this summary to the team?")
    and waits, like `approve`.

  A "talk to a person" request (`handoff: true`, the widget button,
  `POST /v1/conversations/{id}/handoff`) skips intent routing.
- **Prompt-injection defences (AG-03)**, layered so that none relies on the model behaving:
  1. *Input:* blocked topics from the pack get a fixed refusal, and no model sees the request.
     Instruction-like user text is flagged on the trace.
  2. *Sources:* instruction-like lines in retrieved passages and tool results are replaced
     before the model sees them.
  3. *Output:* every answer is checked before it is stored.
     - Images are removed.
     - Links survive only if they point at a cited source.
     - Raw HTML is stripped.
     - An answer that repeats the system prompt is withheld.
  4. *Scope* never comes from text. Tenant, identity and collections come from the verified
     token and configuration. Tool arguments are cut to the tool's schema, and identity is
     filled by the tool gateway (ADR 0019).
- **Red-team set per pack** (`packs/<pack>/eval/redteam.yaml`) covers malicious documents, user
  injection, forged tenants, tool abuse and blocked topics. It runs in CI against an "obedient"
  fake model that does whatever any text it sees asks.

## Consequences

- The pattern lists in `guards.py` are deliberately generic. A determined attacker can phrase
  around them, which is why the output guard and the scope rules do not depend on detection.
  Model-based injection classifiers can be added behind the same functions.
- Fixed: the pack's `agent_defaults.guardrails` used to *replace* the pack's `guardrails` during
  resolution, so blocked topics and the pack's evidence floor (0.6) were lost. They are now
  deep-merged.
  Agents on the offline development models need a lower floor (for example
  `guardrails.min_evidence_score: 0.15`, as in the `dev-offline` retrieval profile), because hash
  embeddings score well below real models.
