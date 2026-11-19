# ADR 0026: Hybrid data plane, split-origin Studio and region cells

Status: Accepted (2026-11-19)

## Context

Phase 4 slice 7 delivers three deployment modes from the backlog:

- **DV-04:** a hybrid mode where the data plane runs in the customer's cluster;
- **DV-08:** a Studio that keeps customer content off the control plane in that mode;
- **DV-07:** region cells, so a tenant's data stays in its region.

The planes, per-service identities and the grouped chart already exist (ADRs 0002, 0017 and DV-02).
This ADR records how the modes are wired and what is still out of scope.

## Decision

- **One chart, two installs.**
  - **Control plane:** the usual SaaS install with `gateway.dataPlaneLink.enabled`.
  - **Data plane:** `values/hybrid-data.yaml`.
    - It disables control-core and control-ops.
    - It adds a `data-core` group with the data plane's own policy decisions (authz and OPA) and
      a **config mirror**.
- **The link is outbound only, with mTLS.**
  - The data-plane gateway has an in-cluster `control-link` listener.
  - Data-plane services reach control-plane services through it (`NEXIQON_SERVICE_URL_<SVC>` is
    set by the chart for every service the release does not run).
  - Envoy connects out with the data plane's client certificate.
  - On the control plane, the `data-plane-link` listener needs a client certificate from the data
    planes' CA and allows only these paths:
    - `ext_authz` checks;
    - the session exchange;
    - signed snapshots;
    - profile resolution;
    - `.well-known` keys;
    - transcript email.

    Everything else gets a 404.
- **The config mirror** (`nexiqon_config_mirror`):
  - pulls each tenant's signed snapshot with its own service identity (`service:config-mirror`,
    allowed `config.snapshots.read` only);
  - verifies the snapshot with the snapshot public keys and caches it on disk;
  - answers the data plane's agent, object and profile lookups from the cache;
  - keeps serving the cached snapshot when the control plane is down;
  - refuses a profile blocked by a security floor (409);
  - is never routed publicly.

  Snapshots now carry resolved model profiles and blocked profiles, so lookups need no call back.
- **Proof (egress test).** `services/conversation/tests/test_hybrid.py` runs the real
  conversation, agent runtime and mirror against the real config service, behind a recorder. A
  question containing a marker phrase is answered, and the control plane sees only
  `GET /v1/snapshots/<env>` requests without the phrase. Answers also continue with the control
  plane down.
- **Keys.**
  - The context-token and snapshot signing private keys (`secrets.yaml`) are mounted only into
    the group running identity and config.
  - Every other group, and every data plane, gets `public-keys.yaml` (verification keys only).
  - A chart test enforces this, and checks that the hybrid profile runs no control-plane service
    and holds no signing key.
  - Dev tooling generates `dev-public-keys.yaml`, and compose uses it for every group except
    control-core.
- **Split-origin Studio (DV-08).**
  - The data plane runs its own Studio at its own origin (`NEXIQON_DATA_ORIGIN` on the control
    Studio, `NEXIQON_PEER_ORIGIN` on the data Studio).
  - The browser calls data-plane services (ingestion, retrieval, agent runtime, conversation,
    channel, tool gateway) on the data origin directly, with that origin's session cookie
    (`SameSite=None` across sites).
  - The data Studio's BFF allows CORS for the peer origin only, with credentials.
  - The CSP `connect-src` names exactly the data origin.
  - Login return addresses accept only the peer origin.

  Documents, conversations and Inspector details therefore never pass through the control plane.
- **Region cells (DV-07).**
  - Identity adds `x-nexiqon-region` to its `ext_authz` answer, read from the token it issued.
  - The gateway strips any client-sent copy, re-picks the route, and sends tenants of a listed
    region to that region's gateway over TLS (`cells` in values).
- **Migrations** run only for the services the release runs (`nexiqon-migrate all --only …`).
  A data plane has no control-plane schemas.
- CI renders and schema-checks the hybrid and cells installs, and validates their Envoy
  configuration with throwaway certificates.

## Consequences and limits

- **Evaluations and the content-gap insight are not supported for hybrid tenants yet.**
  - Both run on the control plane and need the tenant's assistants and conversations, which live
    in the data plane, and the link carries no calls in that direction.
  - The plan is to run evaluation and the gap clustering inside the data plane (a `data-ops`
    group), so only scores and counts come back.
- **Events are not bridged yet.** Audit and metering events from the data plane stay on its NATS.
  Bridging ids-and-counts events (never content) through a NATS leaf node is the next step, and it
  is needed for central audit in hybrid mode.
- **Configuration changes reach a data plane on its next refresh** (default 60 s), or at once on a
  cache miss. A revoked snapshot key needs a mirror restart.
- **Cells share one control plane.** Identity and configuration of record stay central; only data
  and answers are regional.
- **Certificates come from the operator's PKI.** The chart takes Secrets; issuing and rotating
  them (for example with cert-manager) is the operator's job.
