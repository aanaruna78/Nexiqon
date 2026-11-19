# ADR 0024: Tenant lifecycle, retention, backups and notifications

Status: Accepted (2026-11-19)

## Context

Phase 4 asks for four things:
- **G-01:** expired data purged per retention profile, and audited.
- **G-02:** a tenant's deletion and export across every service, tracked, with proof that
  nothing is left.
- **G-03:** backups with a timed restore drill.
- **NT-01:** notifications by email, webhooks and in-app.

## Decision

### Lifecycle endpoints in the service chassis

- Every service answers `POST /v1/_lifecycle/{delete,export,retention}` for the tenant in the
  caller's context. These come from the chassis, so no service can forget them.
- They accept only governance's own verified identity (`service:governance`, ADR 0017) and the
  service-only action `governance.lifecycle.run`. No person, owner or key can call them.
- They are left out of the public contracts.
- `TableLifecycle` (core) is the usual implementation:
  - deletion runs child tables first, with `app.tenant_deletion = on` (the only way append-only
    tables, such as audit and published config, allow deletes);
  - counts are filtered by tenant explicitly as well as by RLS, because outboxes have no RLS;
  - export returns rows as JSON, with secret columns left out.
- Identity removes the organization's row last. People's accounts stay, because they are global.

### Deletion and export are Temporal sagas in governance

- **Deletion:**
  - owner only;
  - the request must carry the organization's id, which Studio fills in only after the owner
    types the address;
  - it waits a grace period (72 hours by default), during which a signal cancels it;
  - it then calls each service in order: config and identity last, governance's own data at the
    end;
  - each step must report `residue_check_passed`, or it is retried with backoff and then fails
    the request;
  - Studio shows every step's progress.
- **What stays after a deletion:** the request and its steps (ids, service names, counts, times)
  are the deletion certificate.
- **Export:** each service's manifest goes to the object store; the parts become one ZIP with a
  `manifest.json`. Only the owner can download it, and it is removed after 7 days.
- **Test coverage:** a test deletes a tenant across real services (authz, channel, identity,
  config, conversation, evaluation, metering, notification). It checks every table is empty for
  that tenant and that another tenant is untouched.

### Retention

- A nightly Temporal schedule (`governance.RetentionAll`) runs one sweep per known tenant. The
  list of known tenants comes from identity's `tenant.created` events and holds ids only.
- A sweep resolves the tenant's own `standard` retention profile from config and asks each
  service to purge what has expired:
  - conversations past their retention date;
  - run traces older than `traces_days`;
  - tool results and arguments older than `tool_results_days` (the call record stays);
  - metering's de-duplication ids after 90 days;
  - export archives after their link lifetime.
- Legal hold purges nothing.
- Each run is recorded with its counts and emits `governance.retention.completed`, which the
  audit service records. Admins can also run a sweep from Studio.

### Backups

- The database is one PostgreSQL with a schema per service, so one logical dump covers every
  service. A Helm CronJob (`backup.enabled`) makes it nightly; managed databases add
  point-in-time recovery.
- `tools/ops/backup_drill.py` times a dump, a restore into a scratch database, and an exact
  row-count comparison of every table.
- The first drill: 59 tables and 20,843 rows, 2.6 seconds, everything matched.
- The other stores, and restore order after a disaster, are in
  `docs/runbooks/backup-restore.md`.

### Notifications

- **Webhooks:**
  - matching events are sent as CloudEvents JSON;
  - each is signed `X-Nexiqon-Signature: t=…,v1=HMAC-SHA256(secret, "t.body")`;
  - sending goes through the SSRF-safe fetcher (public HTTPS only by default, no redirects);
  - failures retry with backoff for up to 6 attempts, and a webhook is switched off after 20
    failures in a row;
  - the signing secret is shown once, and webhook URLs are admin-only because they may carry
    tokens.
- **Retry sweep:** a narrow RLS policy lets the retry loop read pending deliveries across
  tenants (`app.webhook_sweep`); each delivery is then sent in its own tenant's session.
- **In-app inbox:** a few events become items for the roles that act on them, with read state
  per person:
  - budget thresholds go to owners and admins;
  - handovers go to everyone working conversations;
  - evaluation results go to editors;
  - deletion and export progress goes to owners.

  Items carry ids and numbers, never visitors' words.
- **Email** is the service-only channel from ADR 0022.

## Consequences

- Adding a service means adding it to `deploy/groups.yaml`, and its lifecycle is part of every
  deletion and export from then on. A service with tenant data and no real lifecycle fails the
  residue check, not silently.
- The audit chain of a deleted tenant is deleted with it. The governance certificate, which has
  no personal data, is the record that remains.
