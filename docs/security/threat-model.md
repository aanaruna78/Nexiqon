# Threat model (S-01)

Status: reviewed 2026-11-19, at the end of Phase 4. Review again when a trust boundary changes:
a new plane, a new channel, a new kind of tool, or a new hosting mode.

**How to read it.** Each threat has a mitigation **in the code**, with the test or check that
proves it. "Residual" lists what is accepted and why.

## System and trust boundaries

```
 Browser (Studio)  ──OIDC session──►  Studio BFF  ──context token──┐
 Website (widget)  ──widget key────────────────────────────────────┤
 Server (API key)  ──API key───────────────────────────────────────┤
                                                                   ▼
                                                       Edge gateway (Envoy)
                                       strips client context headers, ext_authz → identity
                                                                   │  signed ES256 context token
        ┌──────────────── control plane ───────────────┐   ┌──────────────── data plane ──────────────┐
        │ identity · authz (OPA) · config · audit       │   │ ingestion · retrieval · agent-runtime     │
        │ evaluation · metering · governance · notif.   │   │ conversation · channel · tool-gateway     │
        └───────────────────────────────────────────────┘   │ model-gateway                             │
                         │ service tokens (per-service keys, ADR 0017)                                │
                         ▼                                   └──────────┬───────────────┬────────────┘
        PostgreSQL (schema per service, RLS) · NATS · Temporal · OpenBao · object store
                                                                        │               │
                                                       Customer APIs (tools)   Model providers
```

**Boundaries:**
- **B1:** browser or website to the edge;
- **B2:** edge to services;
- **B3:** service to service;
- **B4:** service to its data stores;
- **B5:** platform to model providers;
- **B6:** platform to customer APIs, websites and webhooks;
- **B7:** tenant to tenant, inside every store.

## STRIDE

| # | Threat | Where | Mitigation | Proof |
|---|---|---|---|---|
| S1 | **Spoofing**: forge a tenant context | B1–B2 | Envoy removes any client `X-Nexiqon-Context`; only identity issues context tokens (ES256, 5 min); every service verifies the signature, issuer and audience | Gateway route config; `nexiqon_core` tenancy tests; isolation harness |
| S2 | Spoofing a platform service | B3 | Per-service signing keys. Verifiers accept a key only for `actor = role = service:<name>`. Each service role has a narrow permission list, and `service_only` actions | ADR 0017; `authz_test.rego`; service-auth tests |
| S3 | Spoofing via a stolen widget key | B1 | Keys work only from their allowed origins, only as end users, only for their assistants (`agt`). A visitor gets their own conversations only | identity access tests; QA3-02 |
| T1 | **Tampering**: change published configuration or audit history | B4 | Append-only triggers on published config versions and the audit chain. Deletes are allowed only with `app.tenant_deletion` inside governance's saga | Migration triggers; audit chain verify; governance tests |
| T2 | Tampering with answers (prompt injection through documents or tools) | Data plane | Sources are quoted as data; input, source and output guards; citations re-verified by retrieval; streaming guard; red-team set | AG-03 red-team suite; `StreamGuard` tests |
| T3 | Tampering with a draft between evaluation and publish | Config / evaluation | Release gate bound to the exact `spec_hash`; a run checks the hash again at the end | Evaluation gate tests |
| R1 | **Repudiation**: deny an action | All | Every write emits an event to the tamper-evident audit chain, with the actor. Gate overrides record the admin and reason. Deletion leaves a certificate | Audit tests; config gate tests |
| I1 | **Information disclosure**: one tenant reads another's data | B7 | RLS (FORCE) on every tenant table, with the app role not the owner; tenant-prefixed workflow ids, blob keys and cache keys; explicit tenant filters in lifecycle code | Isolation tests in every service; governance residue tests |
| I2 | Disclosure inside a tenant (access groups) | Retrieval | ACL filter applied before ranking; classification ceilings per actor type; hidden counts only for staff | Retrieval tests; QA2-04, QA3-06 |
| I3 | Disclosure to model providers | B5 | Model profiles per classification; security floors; PII redaction for cloud providers; restricted data is never sent to a cloud profile | Model-gateway redaction tests; floors |
| I4 | Disclosure through logs or events | Ops | Logs redact secrets and PII (S-02); events carry ids and counts, never content; email addresses are stored hashed | Logging redaction tests; notification tests |
| I5 | SSRF: reach internal services or metadata | B6 | `SafeFetcher` resolves and pins public addresses (no private ranges, no redirects for writes); NetworkPolicy blocks 169.254.169.254 | Fetch tests; tool-gateway abuse suite; chart |
| D1 | **Denial of service**: flood answers or tools | B1 | A request ceiling per gateway pod (Envoy local rate limit); rate limits and circuit breakers on tools; model budgets per profile (hard); input size limits | Gateway config (validated in CI); tool-gateway abuse tests; model budget tests |
| D2 | Use the platform as a mail or HTTP relay | B6 | Email is service-only, limited per recipient and per tenant; webhooks go to public HTTPS only, signed, with retries capped and auto-disable | Notification tests |
| E1 | **Elevation of privilege**: member to admin | B2 | OPA policy: deny by default; `owner_only`, `admin_only` and `service_only` sets; widgets restricted to an action allowlist | `authz_test.rego` (26 cases) |
| E2 | Tool call beyond the user's rights | Data plane | Tools run with the caller's identity; effective risk is the stricter of pack and tool; writes need a confirmation tap; high-risk tools are admin-only | Tool-gateway tests; QA3-03 |
| E3 | Container escape or lateral movement | Runtime | Non-root, read-only root filesystem, all capabilities dropped, no service-account token, no setuid binaries; default-deny NetworkPolicy | Dockerfile; chart; Trivy (HIGH/CRITICAL) |

## OWASP Top 10 for LLM applications (2025)

| Risk | Mitigation | Proof |
|---|---|---|
| **LLM01 Prompt injection** | Sources and tool results are treated as untrusted data, delimited, and neutralised; system prompts never echoed (8-word guard); tools need confirmation for writes; output guard | AG-03 red-team set (`packs/*/eval/redteam.yaml`); guard tests |
| **LLM02 Sensitive information disclosure** | RLS and ACL before retrieval; classification ceilings; redaction to cloud providers; Answer Inspector diagnostics for staff only | Retrieval and model-gateway tests |
| **LLM03 Supply chain** | Dependencies pinned (at least two weeks old, exceptions recorded); lockfiles; Trivy on the filesystem and images; signed images with SBOMs (DV-01, opt-in publishing) | CI security and image jobs |
| **LLM04 Data and model poisoning** | Ingestion scans files (ClamAV), checks sources per tenant, versions documents; outdated pages can be pulled from answers at once; evaluations catch regressions before publish | Ingestion tests; ST-14; QA-02 |
| **LLM05 Improper output handling** | Answers rendered as text, never HTML (Studio and widget); links only `http(s)` with `noopener`; tool arguments validated against JSON Schema | Widget tests; tool-gateway validation |
| **LLM06 Excessive agency** | Tool allowlists per assistant; effective risk; human confirmation for writes; approvals; evaluations never call tools | Tool-gateway tests; evaluation policy |
| **LLM07 System prompt leakage** | Stream guard stops an 8-word run of the system prompt; no secrets in prompts (credentials live in OpenBao, added by the tool gateway) | StreamGuard tests |
| **LLM08 Vector and embedding weaknesses** | Index writes are service-only; tenant and ACL filters inside the vector query; one embedding model per collection | Retrieval index tests |
| **LLM09 Misinformation** | Citations required and verified; abstain when evidence is weak; "Not sure" in the widget; release gate on answer quality | Citation tests; evaluation; W-03 |
| **LLM10 Unbounded consumption** | Model budgets per profile (hard); metering budgets with alerts; token limits per answer; rate limits | Model-gateway budget tests; metering tests |

## Per plane

- **Control plane** (identity, authz, config, audit, evaluation, metering, governance,
  notification):
  - holds keys, policy and the configuration of record;
  - highest-value target: the signing keys, mounted only in their own group (chart check
    `tools/lint/test_helm_chart.py`).
- **Data plane** (ingestion, retrieval, agent-runtime, conversation, channel, tool-gateway,
  model-gateway):
  - handles tenant content and talks to outside systems (B5, B6);
  - in hybrid mode (DV-04, ADR 0026) it runs in the customer's cluster. The link is outbound
    mTLS with a path allowlist on the control side (ext_authz, session exchange, snapshots,
    profile resolution, public keys, transcript email); no content crosses it (egress test
    `services/conversation/tests/test_hybrid.py`). The data plane holds verification keys only.

## Residual risks (accepted)

- **No per-key request rate limit on answers.** There is a per-pod ceiling at the gateway, and
  model budgets bound cost, but one noisy key can use a pod's share. A global rate-limit service
  keyed by key id is planned.
- **Hybrid data planes do not yet forward audit events** to the central audit chain (ADR 0026);
  their actions are audited on their own NATS until the leaf-node bridge ships.

- **The platform image is Debian-slim, not distroless.** The Git connector needs the git binary.
  Mitigations: no package manager use at runtime, no pip, no setuid binaries, read-only
  filesystem, Trivy clean at HIGH/CRITICAL.
- **Studio's CSP allows inline scripts.** Next.js bootstraps inline. Mitigations: no
  third-party scripts, `connect-src 'self'`, every answer rendered as text. A nonce-based CSP
  is planned with Next's nonce support.
- **Model-graded evaluators are not yet used.** Evaluations are deterministic, so they cannot
  judge tone. This is accepted until a reviewed judge exists.
