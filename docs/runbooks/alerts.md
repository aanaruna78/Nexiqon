# Alert runbooks (S-03)

There is one section for each alert in `deploy/observability/prometheus-rules.yaml`. The alerts
are unit-tested with promtool in CI, so each one fires on the condition it describes.

For every alert:
1. Acknowledge it.
2. Check the impact, using the **Look** steps.
3. Fix or mitigate it, using the **Do** steps.
4. Write down what happened (docs/runbooks/incidents.md).

Commands assume the release is installed in the namespace `$NS`.

## NexiqonDeploymentDown

**Critical.** A deployment group (or the gateway or Studio) has had no ready pods for 2 minutes.

**Impact by group:**

| Group down | Effect |
|---|---|
| `gateway` | Nothing reaches the platform |
| `control-core` | Sign-in, permissions and configuration fail everywhere |
| `agent` | Assistants do not answer |
| `knowledge` | Search and indexing stop |
| `tool-gateway` | Actions fail |
| `model-gateway` | Answers fail |
| `control-ops` | Evaluations, metering, governance and notifications pause; answers still work |

**Look:**
- `kubectl -n $NS get pods -l app.kubernetes.io/name=<group>`
- `kubectl -n $NS describe pod …` to see events, image pulls, OOMKilled and probes.
- `kubectl -n $NS logs deploy/<group> --previous`.
- The readiness endpoint, `/readyz`, names the failing dependency (database, Temporal, NATS, OPA).

**Do:**
1. If a dependency is down, fix that first (see below).
2. Bad release: `helm rollback nexiqon <previous revision>`.
3. Out of memory: raise `groups.<group>.resources.limits.memory`.
4. In split mode, only the failing service's pods are affected; the group names tell you which.

## NexiqonPodRestarting

**Warning.** A service container restarted more than 3 times in 30 minutes.

**Look:**
- `kubectl -n $NS logs <pod> --previous`. Look for the last error before the exit:
  configuration, keys not mounted, a migration missing.
- `describe` shows whether it was OOMKilled or a liveness failure.

**Do:**
- Configuration or keys: compare with `values` and the `nexiqon-keys` Secret
  (`tools/dev/k8s_secrets.py` shows the expected files).
- Migration missing: run the migrate Job again (`helm upgrade` re-runs the hook).
- Memory: raise the limit.

## NexiqonHighErrorRate / NexiqonVeryHighErrorRate

**Warning** at more than 5% of requests failing (5xx) for 10 minutes; **critical** at more than
25% for 5 minutes. The alert is per service (`job`).

**Look:**
- The Nexiqon services dashboard: which routes fail, and since when.
- The logs, filtered by `job` and `level=error`. They carry `request_id`, `trace_id` and
  `tenant_id`, never personal data.
- One failing request's trace in Tempo.

**Do, by service:**
- `model-gateway`: a provider is failing.
  - Check the provider's status page.
  - Profiles with a fallback switch over by themselves; for others, deploy a model profile that
    points to another provider (Studio, Settings, Models).
- `retrieval` or `ingestion`: database or embedding model. See NexiqonDatabaseConnectionsHigh.
- `tool-gateway`:
  - Customer APIs failing are 502s for that tool only. The circuit breaker opens by itself.
  - Look at the Actions call log.
- Every service at once: a shared dependency (database, OPA, identity).
  - Check `control-core` first: every request is authorized there.
- After a release: roll back.

## NexiqonSlowAnswers

**Warning.** 95% of answers take more than 20 seconds, for 15 minutes.

**Look:**
- The Answer Inspector on a slow answer shows the time per step: retrieval, model and tools.
- On the dashboard, find which upstream got slower.

**Do:**
- **Model slow:** switch the assistant's model profile, or lower `max_answer_tokens`.
- **Retrieval slow:** see NexiqonSlowSearch.
- **Tools slow:** the tool's `timeout_seconds`; the customer's API.
- **Load:** add `agent` replicas (`groups.agent.replicas`).

## NexiqonSlowSearch

**Warning.** Retrieval search P95 is above its 100 ms budget (RT-08) for 10 minutes.

**Look:**
- Database CPU and connections.
- The size of the largest collections (Knowledge page).
- Whether reranking was switched on for a profile: reranking time is excluded from this metric.

**Do:**
- Scale the database, or raise `hnsw_ef_search` only if recall needs it (it costs time).
- Add `knowledge` replicas.
- Check for an index rebuild in progress (reindex runs).

## NexiqonBackupMissing

**Critical.** The nightly database backup has not succeeded for more than 26 hours.

**Look:**
- `kubectl -n $NS get jobs -l app.kubernetes.io/name=nexiqon-backup`
- `kubectl -n $NS logs job/<last>`. Usually it is credentials (`migrationUrl` in the database
  Secret), the volume being full, or the database being unreachable.

**Do:**
1. Fix the cause.
2. Run a backup now: `kubectl -n $NS create job --from=cronjob/nexiqon-backup manual-$(date +%s)`.
3. Confirm the file exists.
4. On managed PostgreSQL, also confirm the provider's own backups are healthy.

See docs/runbooks/backup-restore.md.

## NexiqonDatabaseConnectionsHigh

**Warning.** PostgreSQL connections are above 80% of `max_connections` for 10 minutes.

**Look:**
- `pg_stat_activity` grouped by `application_name` and `state`. Long `idle in transaction`
  sessions point to a stuck worker.
- Pool sizes: `database.pool_size` times replicas times services per group.

**Do:**
- Lower pool sizes, or put PgBouncer (transaction mode) in front.
- Raise `max_connections` (managed: change the plan).
- Restart the group holding stuck sessions.

## Dependencies (referenced above)

| Dependency | Symptom | Check |
|---|---|---|
| PostgreSQL | `/readyz` reports `database: false` | Provider console; connections; disk |
| OPA | Every request answers 403 or 503 | `kubectl logs deploy/opa`; the policy bundle loaded (`/v1/policies`) |
| Temporal | Indexing, evaluations and deletions do not start | Temporal UI; worker logs (`temporal_unavailable`) |
| NATS | Insights and notifications lag | `nats stream info`; services keep working (events wait in their outboxes) |
| Model provider | `model-gateway` 5xx | Provider status; fallback profile |
