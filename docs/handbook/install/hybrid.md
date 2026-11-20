# Hybrid

In hybrid mode the **data plane** runs in your Kubernetes cluster, next to your data. Everything
that touches your content stays there:

- ingestion and search;
- assistant runs and conversations;
- tools;
- model calls.

Nexiqon runs the **control plane**: sign-in, configuration of record, audit, evaluations and
billing.

```text
 Your cluster (data plane)                         Nexiqon (control plane)
 ┌───────────────────────────────┐  outbound mTLS  ┌──────────────────────────┐
 │ gateway ─ control-link ───────┼────────────────►│ data-plane-link (allowlist)│
 │ knowledge · agent · tools ·   │                  │ identity · config · audit │
 │ models · config mirror        │                  └──────────────────────────┘
 │ PostgreSQL · NATS · storage   │
 └───────────────────────────────┘
```

**What crosses the link.** The link is always outbound from your cluster, uses mutual TLS, and the
control plane accepts only these paths:

- access checks;
- the sign-in exchange;
- signed configuration snapshots;
- model-profile resolution;
- public keys;
- transcript email.

No document, conversation or answer crosses it. An automated egress test proves this on every
change: it asks a question containing a marker phrase, then checks that the control plane never
saw the phrase.

**Configuration.**

- The data plane keeps its own copy of your configuration: a **config mirror** that pulls signed
  snapshots and verifies them.
- If the link is down, assistants keep answering from the last snapshot.

**Studio.** You run a second Studio on your own address. The browser fetches documents,
conversations and Answer Inspector details from it directly, so they never pass through
Nexiqon's cloud.

## Install

1. Ask Nexiqon for the link certificates (your data plane's client certificate and the control
   plane's CA). Create them as the Secret `nexiqon-control-plane-link` (`tls.crt`, `tls.key`,
   `ca.crt`).
2. Create the keys Secret with **public keys only**:
    - `public-keys.yaml` and `service-keys.yaml`;
    - the `identity-*.yaml` of the data-plane services.

   The control plane's signing keys never leave Nexiqon.
3. Install the chart with the hybrid profile:

```bash
helm install nexiqon deploy/helm/nexiqon -f deploy/helm/nexiqon/values/hybrid-data.yaml \
  --set controlPlane.host=<link host from Nexiqon> \
  --set studio.baseUrl=https://ai-data.example.com \
  --set studio.oidc.issuer=https://login.example.com/realms/corp
```

**Current limits.**

- Evaluations and the content-gap insight need your conversations, so they are not yet available
  for hybrid organizations.
- Audit events from the data plane are kept in your cluster until central forwarding ships.
