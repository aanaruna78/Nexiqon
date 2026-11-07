# Nexiqon — Backlog (v3)

[PLAN.md](PLAN.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [UX.md](UX.md) · [REVIEW.md](REVIEW.md)

**Priority:** P0 = pilot gate · P1 = good pilot · P2 = after pilot. **Size:** S ≤ 1 d · M = 2–3 d · L = 4–5 d.
**Definition of done:** contract updated first; unit + contract tests; cross-tenant negative test where data,
events or workflows are touched; traces/metrics; docs; for UI: designed empty/loading/error states, i18n, axe clean.

**Prefixes:** S0 setup · PL platform · ID identity · AZ authz · CF config · EV events/workflows · OB observability ·
M model-gateway · IN ingestion · RT retrieval · AG agent-runtime · T tool-gateway · CV conversation · CH channel ·
QA evaluation · MT metering · G governance · AU audit · NT notification · UX design · ST studio · W widget ·
S security · DV deploy · R pilot · B business

---

## Phase 0 — Platform setup + UX discovery (Weeks 0–2)

| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| S0-01 | Monorepo layout: `services/*`, `libs/` (core, sdk), `contracts/`, `packs/`, `studio/`, `widget/`, `deploy/`; uv workspace + pnpm workspace | `make lint test` green | P0 | M |
| S0-02 | CI: path-filtered per service, lint/type/test, contract checks, audits, gitleaks, trivy, SBOM, cosign | PRs gated | P0 | M |
| S0-03 | **Contracts pipeline**: OpenAPI/AsyncAPI/JSON Schema in `contracts/`; codegen for Python + TS clients; breaking-change detection | Generated clients in CI | P0 | M |
| S0-04 | **`nexiqon-core` chassis v0**: layered settings, logging, OTel, error envelope, health, tenant-context verifier, RLS session, outbox, idempotency, typed clients, two-tenant fixtures | Used by template | P0 | L |
| S0-05 | **Service template** (Copier) generating a service with chassis, Dockerfile, Helm subchart, tests, and stub `tenant.delete` / `tenant.export` handlers | New service runs in < 10 min | P0 | M |
| S0-09 | **Deployment-group runner**: one image per group mounts several services' ASGI apps and workers; service URLs resolved from config so a group can be split with values only (7 groups per REVIEW F1) | Same tests pass grouped and split | P0 | M |
| S0-06 | ADRs for ARCHITECTURE decisions + update design doc to v1.2 (microservices, hybrid, domain packs) | Merged | P0 | M |
| S0-07 | Local dev: Tilt + kind (full), Compose profiles (subset); infra: Postgres+pgvector, Valkey, NATS, Temporal, SeaweedFS (S3), OpenBao, Keycloak, ClamAV, LGTM, Langfuse, Ollama | `make dev` brings stack up | P0 | L |
| S0-08 | Lint rules: no vendor SDK outside adapters; no domain words in core services | CI fails on violation | P1 | S |
| UX-01 | Hands-on competitor teardown (UX.md §2) | UX.md verified | P0 | L |
| UX-02 | Personas, top journeys, journey maps | Reviewed | P0 | M |
| UX-03 | Studio IA + low-fi wireframes (onboarding, knowledge, playground/inspector, domain pack editor) | Reviewed | P0 | M |

## Phase 1 — Platform foundation (Weeks 3–5)

### identity · authz · audit
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| ID-01 | identity service: tenants (region, plan, locale, deployment mode), users, memberships, groups | RLS; contract tests | P0 | M |
| ID-02 | IdP port + adapters: **Clerk** (orgs ↔ tenants, signed webhooks), **Keycloak** (realm template, themed login), **Auth0**/generic OIDC; admin MFA check | Login via each provider in e2e | P0 | L |
| ID-03 | **Tenant-context token**: short-lived, audience-scoped, minted after gateway validation; verifier in chassis | Forged/expired/wrong-audience rejected by every service | P0 | M |
| ID-04 | API keys + widget tokens (hashed, scoped, rotatable, origin allowlist) | Cross-tenant use fails | P0 | M |
| AZ-01 | authz service: OPA with Rego bundles; `decide(actor, action, resource, context)`; decision cache; deny-by-default | Policy unit tests; p99 decision < 10 ms | P0 | M |
| AZ-02 | Base policy set: roles (owner, admin, editor, member, end_user, service), resource types, security floors | Coverage report | P0 | M |
| AU-01 | audit service: consume events, append-only hash-chained store, query API | Tamper test detects edits | P0 | M |

### config (heart of configurability)
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| CF-01 | Config registry: typed objects (domain pack, agent, graph, tool, model profile, retrieval profile, channel, retention profile), JSON Schema per type, versioning, immutability on publish | CRUD + versions | P0 | L |
| CF-02 | **Layered resolution** (platform → deployment → region → tenant → pack → agent → channel → env) with **security floors** | Property tests: floors never loosened | P0 | L |
| CF-03 | Environments + promotion (dev → staging → prod), diff, rollback | Promote/rollback e2e | P0 | M |
| CF-04 | Domain Pack format v1 (ARCHITECTURE §6.2), validator, import/export (YAML), GitOps sync | Pack round-trips losslessly | P0 | L |
| CF-05 | Config snapshot distribution to data plane (pull + signed bundles) | Data plane runs from snapshot if control plane is down | P0 | M |
| CF-06 | Feature flags (OpenFeature + flagd) | Flag per tenant | P1 | S |

### events · workflows · observability · platform
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| EV-01 | NATS JetStream: CloudEvents envelope, outbox relay, consumer chassis (retries, DLQ, idempotency), tenant context in event | Redelivery causes no duplicate effects | P0 | M |
| EV-02 | Temporal: deployment, worker chassis, tenant-context propagation | Workflow can't act on other tenant | P0 | M |
| OB-01 | Distributed tracing + metrics + logs end to end (gateway → services → events → workflows), dashboards per service, SLO templates | One trace across 3 services | P0 | M |
| PL-01 | Gateway: Envoy Gateway routes, JWT validation, rate limits per tenant/key, CORS, request size limits | Gateway conformance tests | P0 | M |
| PL-02 | Service-to-service mTLS (Linkerd) + network policies | Unmeshed call rejected | P1 | M |
| PL-03 | **Cross-service isolation harness**: two tenants; auto-discover routes/consumers/workflows; negative cases in CI | New endpoint without case fails CI | P0 | L |
| PL-04 | Seed + fixtures: two demo tenants, SaaS KA pack installed | `make seed` idempotent | P1 | S |

### design system · Studio shell
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| UX-04 | Tokens (colour, type, spacing, motion), light/dark, **tenant theming** | Contrast AA | P0 | M |
| UX-05 | Component library (shadcn/ui + Radix) in Storybook incl. tables, forms, status, code, charts | a11y tests per component | P0 | L |
| UX-06 | i18n (next-intl, ICU), RTL, UX writing guide; **domain vocabulary injection** from packs | Pseudo-locale + RTL OK; labels change with pack | P0 | M |
| ST-01 | Studio shell + BFF: auth adapter (Clerk/OIDC), org switcher, IA nav, ⌘K palette | Keyboard-only nav | P0 | M |
| ST-02 | **Schema-driven settings forms** (JSON Schema + UI hints → our components) | New config field appears without UI code | P0 | L |
| ST-03 | Members, roles, API keys, audit log viewer | Usability check | P1 | M |
| UX-07 | End-of-phase usability test | Findings triaged | P1 | S |

## Phase 2 — Knowledge plane (Weeks 6–10)

### model-gateway
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| M-01 | Service + provider port; model profiles from config; capability flags | Swap profile by config | P0 | M |
| M-02 | Adapters: OpenAI-compatible (OpenAI, vLLM, Ollama), Anthropic, Gemini; normalized tools + structured output + streaming | Same contract tests on all | P0 | L |
| M-03 | Embeddings (OpenAI @1024, Qwen3-Embedding-0.6B) + reranker (Qwen3-Reranker) | 1024-d from both | P0 | M |
| M-04 | **Hybrid routing** by data classification + tenant data policy floor | Forbidden provider never called (test) | P0 | M |
| M-05 | Budgets, usage/cost events, PII redaction hook, timeouts, fallback | Budget breach → graceful refusal | P0 | M |
| M-06 | vLLM recipe (Compose + Helm), GPU sizing guide | Runs on target GPU | P0 | M |
| M-07 | **Model bake-off** on eval set; licence check; pick defaults | Report per profile | P0 | M |

### ingestion
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| IN-01 | Service + **plugin SDK** for connectors/parsers/chunkers (manifest, config schema, capabilities) | Plugin added without core change | P0 | L |
| IN-02 | Ingestion as **Temporal workflow**: fetch → scan → parse → chunk → embed → index; progress events; retries; idempotent | Killed worker resumes | P0 | L |
| IN-03 | Connectors: file upload, **web/sitemap crawler** (robots, filters, schedule, change detection), S3 bucket, Git repo | Crawl docs site; only changes re-embedded | P0 | L |
| IN-04 | SSRF-safe fetcher (shared lib with tool-gateway) | Security tests pass | P0 | M |
| IN-05 | Malware scan (ClamAV port) + quarantine | EICAR quarantined | P0 | S |
| IN-06 | Parsers: PDF, DOCX, MD, TXT, HTML, CSV/JSON with page/section coordinates; chunkers (heading-aware, token) | Golden files | P0 | L |
| IN-08 | **Document tree**: build document › section › chunk nodes with `parent_id` + `ltree` path from parser headings; tree kept consistent on replace/delete | Tree golden files; deleting a section removes its subtree | P0 | M |
| IN-09 | **Summary nodes** (RAPTOR-style): section + document summaries embedded and indexed; regenerated on change; cost-capped | Kept only if RT-05 shows gain on broad questions | P1 | M |
| IN-07 | Versioning, reindex workflow on embedding change, deletion propagation events | Old/deleted content unretrievable | P0 | M |

### retrieval
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| RT-01 | Service + **vector-store port** (pgvector adapter; capability: filter-before-rank) | Adapter contract tests | P0 | M |
| RT-02 | Hybrid search (vector + language-aware FTS), RRF, dedupe, optional rerank; profiles from config | ACL-restricted chunks never returned | P0 | L |
| RT-03 | Answer contract + **citation verification** + abstain threshold | Fabricated citation stripped | P0 | M |
| RT-04 | Q&A snippets source type | Snippet outranks stale docs | P1 | S |
| RT-05 | Retrieval eval harness + SaaS KA gold set (multilingual subset) | Recall@5 in CI | P0 | M |
| RT-06 | Signed download URLs with authz | Cross-tenant URL fails | P1 | S |
| RT-07 | **Small-to-big retrieval**: expand hits to parent section within token budget; merge sibling hits; **section-path citations** | Recall@5 and citation support ≥ flat baseline | P0 | M |
| RT-08 | Retrieval latency budget: P95 < 100 ms (excl. reranker) tracked in eval harness and dashboards | Alert on breach | P1 | S |

### Knowledge UI
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| ST-04 | Knowledge UI: add sources (connector gallery from plugin manifests), live progress, errors with fix hints, re-sync, replace, delete with impact preview, access rules | Add docs site < 3 min | P0 | L |
| ST-05 | Basic Playground with citations | Source preview renders | P0 | M |
| UX-08 | End-of-phase usability test | Triaged | P1 | S |

## Phase 3 — Agent plane (Weeks 11–15)

| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| AG-01 | agent-runtime: **declarative graph compiler** (graph config → LangGraph), node library (route, retrieve, classify, call_tool, clarify, validate_evidence, approve, escalate, respond) | SaaS KA graph runs from config only | P0 | L |
| AG-02 | Checkpointer (tenant-scoped), interrupts/resume, capability-aware (guided JSON for weaker models) | Passes on cloud + small on-prem profile | P0 | M |
| AG-03 | Prompt-injection defences + red-team set (malicious docs, forged tenant IDs, tool abuse) | Suite passes | P0 | M |
| T-01 | tool-gateway: registry from config, strict schema validation, authz, egress allowlist, circuit breaker, idempotency, result minimization, audit events | Fuzz: zero unauthorized calls | P0 | L |
| T-02 | Secrets port (OpenBao, cloud SMs via ESO); resolution only inside adapters | No secret in prompts/logs/events (tested) | P0 | M |
| T-03 | Tool adapters: declarative REST, **OpenAPI import**, human-approval tool | Add account-lookup tool with no code | P0 | M |
| T-04 | Demo mock APIs (account/subscription, ticketing) for two tenants | In dev stack | P0 | M |
| CV-01 | conversation service: sessions, messages, provenance, feedback, retention from config | Answer contract persisted | P0 | M |
| CV-02 | Handoff/escalation: rules from pack, summary generation, ticket via tool-gateway | Low evidence → escalation with summary | P0 | M |
| CH-01 | channel service: channel plugin port, web/API channels, SSE streaming events | Stream carries citations + tool status | P0 | M |
| ST-06 | **Assistant builder**: create from domain pack, behaviour, knowledge, model profile, versions with diff + rollback | Publish without docs | P0 | L |
| ST-07 | **Answer Inspector** (UX G1) | Root-cause bad answer ≤ 3 min | P0 | L |
| ST-08 | "View as" user/group (G5) | Exact retrievable sources | P1 | M |
| ST-09 | Actions UI: OpenAPI import, credential binding, risk badge, allowlist, dry-run console, approvals log (G6) | Add tool < 10 min | P0 | L |
| ST-10 | **Domain Pack editor**: vocabulary, intents, prompts, guardrails, starter questions; import/export; validation | Create 2nd pack in Studio | P0 | L |
| ST-11 | Graph viewer (read-only visual of declarative graph) | Shows active branches in Inspector | P1 | M |
| ST-12 | Models & data policy settings incl. hybrid routing rules (G7) | Admin understands data flow (test) | P1 | M |
| T-05 | Tool authorization + abuse suite | Zero unauthorized actions | P0 | M |
| W-00 | **Basic widget cut** for the preview: streaming, citations, handoff button, theme colour | Embeds on partner's docs site | P0 | M |
| UX-09 | End-of-phase usability test | Triaged | P1 | S |

### Design-partner preview (week 16, tentative)
| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| DP-01 | Dedicated single-tenant deployment on DigitalOcean (DOKS, Managed PG + pgvector, Valkey, Spaces) from the Helm chart | Partner environment reachable with TLS, backups on | P0 | M |
| DP-02 | Partner onboarding: SaaS KA pack configured, their docs ingested, account-lookup tool against their sandbox API | Partner admin gets cited answers on own docs | P0 | M |
| DP-03 | Preview SOW: scope, limitations (pre-gate, single tenant), data handling, feedback cadence, IP | Signed | P0 | S |
| DP-04 | Weekly feedback loop: usage review, UX findings into backlog | Findings logged weekly | P1 | S |

## Phase 4 — Product + operations (Weeks 16–19)

| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| W-01 | Widget (Lit Web Component): streaming, citations, theming, light/dark, vocabulary from pack | < 60 KB gz; plain HTML/React/WordPress | P0 | L |
| W-02 | Widget i18n, RTL, WCAG 2.2 AA | Screen-reader walkthrough | P0 | M |
| W-03 | Honest uncertainty, one-tap handoff, transcript email, action confirmation cards | Write requires tap | P0 | M |
| W-04 | Feedback + suggested questions | Feeds metering | P1 | S |
| ST-13 | **Onboarding wizard** (pick domain pack → add source → test → embed) | ≤ 10 min to first cited answer (4/5 users) | P0 | L |
| ST-14 | One-click fix loop (G2) | ≤ 3 min | P0 | M |
| ST-15 | Channel settings: widget editor with live preview, origins, snippet | Embed ≤ 5 min | P0 | M |
| ST-16 | Conversations review + escalation queue | Review 20 convos quickly | P1 | M |
| QA-01 | evaluation service: test sets, runs (Temporal), evaluator plugins, scorecards, `GET /v1/evaluations/reports` | Scorecard per version | P0 | L |
| QA-02 | **Safe publish gate** (G4) on config publish/promotion | Regression blocks publish | P0 | M |
| ST-17 | Evaluations UI | Test set from conversations | P1 | M |
| MT-01 | metering service: usage/cost read models, quotas, budgets, alerts | Matches gateway accounting | P0 | M |
| MT-02 | Insights: quality, **content-gap clustering** (G3), domain KPIs from pack | Useful in usability test | P1 | L |
| ST-18 | Insights + cost UI (G3, G8) | — | P1 | M |
| G-01 | governance: retention workflows per profile | Expired data purged, audited | P0 | M |
| G-02 | **Tenant deletion/export sagas** across all services (Temporal), tracking UI | Every service confirms deletion; test proves no residue | P0 | L |
| G-03 | Backups + timed restore drill per data store | Documented | P0 | M |
| NT-01 | notification service (SMTP, webhooks, in-app) | Alerts deliver | P1 | M |
| DV-01 | Hardened images (non-root, distroless), signed | trivy clean | P0 | M |
| DV-02 | **Helm umbrella chart** with subcharts, deployment-group values (7 groups or split), and SaaS / hybrid / private profiles | Installs on kind + DOKS | P0 | L |
| DV-03 | OpenTofu module **DigitalOcean** (DOKS, Managed PostgreSQL, Managed Valkey, Spaces, Container Registry, Load Balancer, VPC, GPU Droplet pool) | Staging applied from scratch | P0 | L |
| DV-03b | OpenTofu modules: AWS, GCP, Azure (same ports) | `plan` validates; one applied before first non-DO customer | P1 | L |
| DV-04 | **Hybrid data-plane mode**: data plane install in separate cluster, outbound-only link to control plane, config snapshot pull, redacted telemetry | Data stays in data plane (egress test) | P0 | L |
| DV-05 | Single-node Compose bundle + GPU vLLM | Install < 1 h | P1 | M |
| DV-06 | Air-gapped bundle (images, weights, chart, offline licence) | Installs offline | P1 | M |
| DV-07 | Region cells (tenant.region routing) | Data stays in cell | P1 | M |
| DV-08 | **Split-origin Studio for hybrid**: document content, conversations and Inspector details are fetched by the browser directly from the customer's data-plane gateway; control plane sees metadata only | Egress capture shows no customer content reaching control plane | P0 | M |
| DV-09 | **Minimum on-prem footprint profile**: Linkerd, LGTM, Langfuse optional (OTLP to customer's stack); documented sizing | Runs on 1 CPU node + 1 GPU node | P1 | M |
| S-01 | Threat model (STRIDE + OWASP LLM Top 10), per-service and per-plane | Reviewed | P0 | M |
| S-02 | Hardening: CSP, headers, network policies, PII log redaction, dependency pinning | Checklist complete | P0 | M |
| S-03 | Incident runbooks + alerting per service | Alerts fire in test | P0 | M |
| UX-10 | a11y audit + 2 additional UI languages | Zero criticals | P0 | M |
| UX-11 | Visual regression + performance budgets in CI | Enforced | P1 | M |
| D-01 | Docs site: quickstart, domain pack guide, plugin SDK guide, API ref, install guides (SaaS/hybrid/private) | Published | P1 | L |

## Phase 5 — Pilot readiness (Weeks 20–22)

| ID | Work item | Acceptance | Pri | Size |
|---|---|---|---|---|
| R-01 | §13 demo e2e on **Shared SaaS** and **Hybrid** | Green on both | P0 | M |
| R-02 | **Customer Support domain pack** end to end with **zero code change** | Diff shows only `packs/` changed | P0 | M |
| R-03 | Staging on DigitalOcean (DV-03) + hybrid data plane on a separate DOKS cluster with a GPU Droplet (simulated customer) | Both reachable | P0 | M |
| R-04 | Load tests per service; P95 + cost-per-resolution baselines; autoscaling (HPA/KEDA) tuned | Recorded | P1 | M |
| R-05 | Chaos tests: kill services/NATS/Temporal workers; system degrades gracefully | Runbook validated | P1 | M |
| R-06 | **Independent** security review / pen test; fix criticals | No open criticals | P0 | L |
| R-07 | Final usability study (5–8 users) vs UX.md §6 | Targets met | P0 | M |
| R-08 | §15 gate sign-off | All evidenced | P0 | S |

## B — Business / legal (parallel)

| ID | Work item | Pri | When |
|---|---|---|---|
| B-01 | IP / work-for-hire review; define retained platform IP (incl. domain packs, plugins) | P0 | Weeks 0–2 |
| B-02 | DPAs: OpenAI, Anthropic, Google, Clerk, Auth0, cloud | P0 | Weeks 1–10 |
| B-03 | Open-model licence review (Qwen, gpt-oss) for on-prem redistribution | P0 | Weeks 7–11 |
| B-04 | Global privacy pack (GDPR, UK, CCPA, DPDP) + hybrid-mode responsibility matrix | P0 | Weeks 10–18 |
| B-05 | Pilot SOW template | P0 | Weeks 8–16 |
| B-06 | Cost model per deployment mode → pricing hypotheses | P1 | Weeks 12–20 |
| B-07 | Pilot pipeline: 2–3 SaaS KA candidates, ≥1 hybrid; **design partner chosen by week 12** | P0 | Ongoing |
| B-08 | Book independent security reviewer | P0 | By week 14 |

## Deferred (P2)

Knowledge-graph port (entities/relations, Postgres adapter first; graph DB only if evals prove need), Dedicated SaaS automation, SAML/SCIM, multi-region active cells, Qdrant/OpenSearch/Milvus adapters, Kafka adapter,
Azure Blob native, OCR, more connectors (Confluence, SharePoint, Notion, Zendesk), Slack/Teams/WhatsApp channels,
third-party plugin sandbox and marketplace, visual graph **editor**, single-binary all-in-one mode, advanced autonomy.

---

## First sprint (Weeks 0–2)

1. S0-01 → S0-03 → S0-04 → S0-05 (platform skeleton is the multiplier for every later service)
2. S0-07 dev environment, S0-02 CI, S0-06 ADRs
3. UX-01 → UX-02 → UX-03 in parallel
4. B-01, B-07 started
