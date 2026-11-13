# ADR 0019: Tool gateway, confirmations and the secrets port

Status: Accepted (2026-11-13)

## Decision

- **One way out.** Assistants act on business systems only through tool-gateway. Tools are `tool`
  config objects: versioned, published and deployed like everything else. The gateway reads them,
  and each agent's tool allowlist, with its own narrow service identity. Invocations run as the
  **caller** (their token).
- **Checks on every call**, in order:
  1. the tool is deployed;
  2. it is on the agent's allowlist;
  3. OPA allows `tool.invoke.<risk>` (high-risk tools are admin-only);
  4. the arguments are valid against the tool's input schema, within a size limit;
  5. writes carry the caller's confirmation;
  6. idempotency;
  7. the rate limit and the circuit breaker.
- **Identity is not an argument.** `{caller.actor_id}` and `{caller.tenant_id}` placeholders in URL
  templates come only from the verified token. A model cannot look up someone else's record.
- **Confirmations.** For writes, the gateway records exactly what will run: tool, arguments hash,
  actor and expiry. The caller approves it, and only that call can use it, once. agent-runtime's
  `approve` node creates it, and `call_tool` replays the confirmed arguments rather than asking the
  model again. "Human approval" tools create tasks that staff decide.
- **Egress.**
  - Requests go through the SSRF-safe fetcher, pinned to the checked address.
  - The host must be on the tool's own allowlist.
  - Path arguments are URL-encoded.
  - Redirects are not followed.
  - Plain http is refused unless `allow_insecure_http` is set (development only).
- **Secrets port.** Credentials are stored per workspace (OpenBao KV v2 under `tenants/<id>/`).
  They are write-only through the API, resolved only inside the gateway at call time, and scrubbed
  from upstream errors and results. They are never logged, emitted or stored with call records.
- **Results** are minimised to the tool's output schema, capped in size, and labelled with the
  tool's `result_classification`, which drives the model-routing rules (ADR 0010).
- **OpenAPI import** turns operations into tool definitions (risk follows the HTTP method), saved
  as drafts through config.

## Consequences

- The rate limiter and circuit breaker are per process; a shared limiter (Valkey) is a later step.
- Tool definitions now require `host_allowlist`. Plain-http URLs pass the schema, but the gateway
  refuses them unless `allow_insecure_http` is set.
