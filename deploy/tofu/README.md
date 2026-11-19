# Infrastructure (DV-03)

`modules/digitalocean` creates everything the chart needs outside Kubernetes on DigitalOcean, the
first reference cloud (ADR 0014):
- a private VPC;
- a DOKS cluster with autoscaling, surge upgrades, HA control plane from 3 nodes and an optional
  tainted GPU pool;
- managed PostgreSQL 16 with an owner role and a separate application role (row-level security
  applies to it), a transaction pool for the application, and a firewall that admits only the
  cluster;
- managed Valkey;
- a private, versioned Spaces bucket;
- optionally the account's container registry.

`envs/staging` uses the module with remote state in Spaces. The provider is pinned exactly
(2.107.0, older than two weeks) and the lock file is committed.

```bash
export DIGITALOCEAN_TOKEN=... SPACES_ACCESS_KEY_ID=... SPACES_SECRET_ACCESS_KEY=...
export AWS_ACCESS_KEY_ID=$SPACES_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$SPACES_SECRET_ACCESS_KEY
cd deploy/tofu/envs/staging
tofu init -backend-config="bucket=<state-bucket>"
tofu plan -out staging.plan && tofu apply staging.plan
tofu output -raw kubeconfig > ~/.kube/nexiqon-staging
```

Then:
1. Create the chart's Secrets. `nexiqon-database` comes from the `database_url` and
   `database_migration_url` outputs.
2. Install an ingress controller and cert-manager.
3. Run NATS (JetStream) and Temporal, for example with their official charts in `nexiqon-infra`.
4. `helm install nexiqon deploy/helm/nexiqon -f deploy/helm/nexiqon/values/saas.yaml`.

**PostgreSQL extensions.** The retrieval migration creates `vector` and `ltree`. If the owner role
may not create extensions on your plan, run `CREATE EXTENSION vector; CREATE EXTENSION ltree;`
once as `doadmin`.

**Status.** `tofu fmt` and `tofu validate` run in CI (no credentials, no backend). Applying to a
real account has not been done yet and needs a DigitalOcean token. Modules for AWS, GCP and Azure
(DV-03b) follow the same outputs.
