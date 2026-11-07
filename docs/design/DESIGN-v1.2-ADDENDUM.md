# Nexiqon Technical Design: v1.2 Addendum

Applies to: *Nexiqon by ThinkHiveLabs: Technical Architecture & Product Strategy v1.1* (07 Nov 2026).
Status: Accepted, 07 Nov 2026 (work item S0-06). Where this addendum and v1.1 differ, this addendum wins.
Details: [ARCHITECTURE.md](../plan/ARCHITECTURE.md), [PLAN.md](../plan/PLAN.md), [ADRs](../adr/README.md).

| v1.1 section | v1.1 position | v1.2 change | ADR |
|---|---|---|---|
| §3 Logical architecture, §15 risks | Modular monolith to limit operational load | **Microservices** along bounded contexts, packaged as **6 deployment groups + edge** for the MVP; split by config later | 0002 |
| §3 | Single trust boundary | **Control plane / data plane** split; enables **hybrid** (customer-hosted data plane) | 0003 |
| §6 Identity | OIDC/OAuth2 | Clerk (SaaS), Keycloak (on-prem), Auth0/OIDC behind one port; signed **tenant-context token** verified by every service | 0009 |
| §6 Database | Tenant IDs + RLS | Unchanged in principle; now **schema per service**, FORCE RLS, non-owner roles, transaction-local context | 0005 |
| §3 LLM gateway | Provider routing | **Model profiles** (cloud frontier / on-prem vLLM, Qwen family); 1024-d embeddings; hybrid routing by data classification | 0010 |
| §1 Templates | Product templates | Templates become **Domain Packs** (configuration); core is domain-agnostic; second pack (Customer Support) must need zero code | 0011 |
| §4 RAG | Hybrid retrieval with citations | Adds **document tree**, small-to-big retrieval and section-path citations; **no graph database** | 0012 |
| §8 Deployment | Three offerings | Four modes: Shared SaaS, Dedicated SaaS, **Hybrid**, Private; **DigitalOcean** first reference cloud; Helm + OpenTofu | 0014 |
| §12 Roadmap | 11 weeks, one engineer + part-time help | **About 23 weeks** to the pilot gate, all roles in-house, UX-first; design-partner preview at about week 16 (tentative) | — |
| New | — | **Events** via NATS JetStream + transactional outbox; **Temporal** for cross-service sagas; **OPA** for authorization | 0006–0008 |

Unchanged: functional requirements FR-01 to FR-07, the security invariants and acceptance tests (§6), the privacy
and retention rules (§7), the quality targets (§11), the demo scenario (§13) and the pilot release gate (§15).
