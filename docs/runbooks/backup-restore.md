# Backup and restore (G-03)

What is backed up, how often, how to restore it, and how long a restore took in the last drill.

## Targets

| | Target |
|---|---|
| RPO (data you can lose) | 24 hours for logical dumps; 5 minutes where point-in-time recovery is on (managed PostgreSQL) |
| RTO (time to be back) | 1 hour for the platform database; the drill must stay well under it |

## Data stores

| Store | Holds | Backup | Restore |
|---|---|---|---|
| **PostgreSQL** (one database, a schema per service) | Everything durable: tenants, config, documents' index, conversations, runs, audit chain, metering, governance certificates | Managed (DigitalOcean): daily backups and 7-day point-in-time recovery, from `deploy/tofu`. Also, or self-hosted: the nightly `pg_dump -Fc` CronJob (`backup.enabled`, kept `keepDays`) | Point-in-time: restore the cluster from the provider console or API to a new cluster, then point `nexiqon-database` at it. Logical: `pg_restore --no-owner -d <new db> nexiqon-<stamp>.dump`, then run `nexiqon-migrate all` (it does nothing when already current) |
| **Object store** (Spaces / S3 / SeaweedFS) | Original uploaded files, export archives | Bucket versioning plus cross-region replication on Spaces/S3. SeaweedFS: `weed backup` per volume, or replication | Copy the objects back (`aws s3 sync`), or switch the bucket to the replica. The index (PostgreSQL) refers to objects by key, so restore both from the same point in time |
| **OpenBao** | Tool credentials | Raft snapshots: `bao operator raft snapshot save` (nightly, encrypted, stored off-cluster) | `bao operator raft snapshot restore`; unseal keys are held as the operator's runbook says |
| **Keycloak** (bundled IdP) | Users and logins, for installs that use it | Its own PostgreSQL database: back it up like the platform database | Restore its database; realm import (`files/keycloak-realm.json`) recreates the configuration |
| **Temporal** | Running workflows (ingestion, evaluation, governance) | Its own database (managed Temporal or its PostgreSQL) | Workflows in flight resume from their history; finished work is already recorded by the services |
| **NATS JetStream** | Events in flight | None needed: every event comes from a service outbox in PostgreSQL. After a restore, unpublished outbox rows are published again; consumers de-duplicate by event id | — |
| **Valkey** | Caches, rate limits | None: rebuilt on demand | — |

## The drill (every release)

```bash
make dev-up PROFILES=platform,apps          # or point COMPOSE at a staging copy
uv run python -m tools.ops.backup_drill     # dump, restore into nexiqon_drill, compare, drop
```

The drill:
1. dumps the whole database;
2. restores it into a scratch database;
3. compares exact row counts for every table in every service schema;
4. drops the scratch database;
5. prints the time of each step.

It fails if any table comes back with fewer rows.

In Kubernetes:
1. Run the CronJob's image as a one-off Job (`kubectl create job --from=cronjob/nexiqon-backup drill`).
2. `pg_restore` the newest dump into a scratch database on the same server, compare counts the
   same way, and drop it.
3. For managed PostgreSQL, restore the latest backup to a new cluster and compare.

### Results

| Date | Where | Database | Tables | Rows | Dump | Restore | Verify | Total | Result |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-19 | Local stack (compose, PostgreSQL 16.10) | 27.8 MB | 59 | 20,843 | 0.73 s | 1.43 s | 0.43 s | 2.59 s | All tables match |

Add a row after each drill. A drill that takes longer than a quarter of the RTO is a finding.

## Restore order after a disaster

1. **PostgreSQL** (platform database). Then run `nexiqon-migrate all`.
2. **Object store**, from the same point in time.
3. **OpenBao**, then unseal it.
4. **Keycloak**, if bundled.
5. **Temporal.**
6. **Start the services.** Outboxes republish, and consumers skip events they have already
   processed.
7. **Check.** `/readyz` on every group, the audit chain (`audit/v1/chain/verify`), and one search
   and one answer per tenant.
