# Incident response (S-03)

## Severity

| Severity | Examples | Response |
|---|---|---|
| **SEV1** | Platform down; one tenant's data visible to another; secrets exposed | Page now; all hands; customer notice within 24 h where data is involved |
| **SEV2** | One capability down for everyone (answers, search, sign-in); data loss risk (backups failing) | Page now; fix or roll back within 4 h |
| **SEV3** | Degraded for some (slow answers, one tenant's indexing stuck, one tool failing) | Same working day |
| **SEV4** | Cosmetic, or with a workaround | Backlog |

## The first 15 minutes

1. **Acknowledge** the page, and say in the incident channel that you are on it.
2. **Assess** with the alert's runbook (docs/runbooks/alerts.md): who is affected, and since when.
3. **Mitigate before fixing.** The usual mitigations:
   - **Roll back:** `helm rollback`, or roll back an assistant in Studio, Versions.
   - **Switch model profile:** for a provider outage.
   - **Disable a tool:** remove it from the assistant's allowlist.
   - **Pause a channel:** revoke the widget key.
4. **Communicate:** status page and affected tenants, for SEV1 and SEV2.

## Security incidents

### Suspected cross-tenant access

1. Find the requests by `request_id` or `trace_id`. Every log line and audit event carries
   `tenant_id` and `actor_id`.
2. Check the audit chain: `GET /audit/v1/chain/verify` for each affected tenant.
3. Confine:
   - revoke the keys or sessions involved;
   - suspend the tenant if needed (identity `tenant.suspended`).
4. Keep the evidence: audit export, logs and traces. Do not delete or rotate anything that could
   destroy evidence until it is copied.

### Leaked credential

What to do depends on what leaked:

| What leaked | What to do |
|---|---|
| Widget or API key | Revoke it in Studio (API keys or the assistant's Widget tab) and issue a new one |
| Tool credential | Rotate it at the provider; update it in Studio (Actions, Credentials); it is stored in OpenBao |
| Context-token or service signing key | Add a new key id, deploy, then remove the old one from `public_keys`. Tokens live 5 minutes, so the old key can go shortly after |
| Webhook secret | Remove the endpoint and add it again (the new secret is shown once) |

### Prompt injection or jailbreak in production

1. Find the run in the Answer Inspector: the guard steps show what was blocked or let through.
2. Add the case to the pack's `redteam.yaml`, and to a test set so the release gate covers it.
3. Tighten the guardrails in the Domain Pack or the assistant; publish through the gate.

## After the incident

Within 5 working days, write a blameless review (template below) in `docs/qa/incidents/`. Turn
each action into a backlog item.

```markdown
# Incident <date>: <title>
Severity · Duration · Tenants affected
## What happened (timeline, UTC)
## Impact
## Why (root cause and contributing factors)
## What went well / what did not
## Actions (owner, due)
```

## Service quick reference

| Service | Owns | If it is down |
|---|---|---|
| identity | Tenants, sign-in, keys | Nobody can sign in or call the API |
| authz | Permission decisions (OPA) | Every request is refused (fails closed) |
| config | Assistants, packs, profiles, versions | Running assistants keep their cached config for a while; changes fail |
| audit | Tamper-evident event log | Events wait in the bus; nothing is lost |
| evaluation | Test sets, runs, release gates | Gated publishes fail closed (admins can override) |
| metering | Usage, budgets, insights | Insights pause; events wait |
| governance | Retention, deletion, export | Sweeps and requests wait (Temporal resumes them) |
| notification | Email, webhooks, inbox | Notifications wait; webhooks retry |
| ingestion | Sources, documents, indexing | New content waits; answers keep working |
| retrieval | Search, citations | Answers fail ("unavailable"), honestly |
| agent-runtime | Answering | Assistants do not answer |
| conversation | Conversations, handover | Widget and API chats fail |
| channel | Widget settings | The widget cannot load its settings |
| tool-gateway | Actions | Actions fail; answers without actions still work |
| model-gateway | Models | Answers fail; fallback profiles help |
