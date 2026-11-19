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

## AWS, Google Cloud and Azure (DV-03b)

`modules/aws`, `modules/gcp` and `modules/azure` build the same things with each cloud's managed
services, and expose the same outputs (`database_url`, `database_migration_url`, `valkey_uri`,
`bucket`, `registry_endpoint`, plus how to reach the cluster):

| | Network | Kubernetes | PostgreSQL 16 (pgvector) | Cache | Files |
|---|---|---|---|---|---|
| AWS (`hashicorp/aws` 6.71.0) | VPC, two private and two public subnets, NAT | EKS, KMS-encrypted Secrets, optional NVIDIA pool | RDS, encrypted, TLS forced, 14-day backups, optional Multi-AZ | ElastiCache Valkey 8, TLS | S3, private, versioned, KMS |
| Google Cloud (`hashicorp/google` 8.9.0) | VPC, Cloud NAT, private services access | GKE regional, private nodes, Workload Identity, network policy, optional L4 pool | Cloud SQL, private IP only, encrypted connections, point-in-time recovery, optional regional HA | Memorystore for Valkey 8 | Cloud Storage, uniform access, public access prevented |
| Azure (`hashicorp/azurerm` 5.12.0) | VNet with a delegated database subnet and private DNS | AKS with Cilium network policy, workload identity, optional GPU pool | Flexible Server, private only, `VECTOR,LTREE` allowed, TLS, optional zone-redundant HA | Azure Managed Redis (Valkey protocol) | Blob Storage (ZRS, versioned, reachable from the node subnet only) |

Notes:
- **The application role.** On AWS and Azure the provider cannot create database roles. Run the
  `app_role_sql` output once as the owner. Cloud SQL creates both roles; its `app_role_sql` only
  grants `CONNECT`.
- **Azure Blob does not speak S3.** Set `blobs.backend: azure` with `endpoint = blob_endpoint`,
  `bucket`, `access_key = blob_account` and `secret_key = blob_account_key`. The adapter
  (`nexiqon_core/adapters/azure_blob.py`) is tested against Azurite.
- **Google Cloud Storage** is used through its S3-compatible endpoint with HMAC keys of a
  service account.
- Providers are pinned exactly, to releases more than two weeks old. Lock files belong to the
  environment that uses a module.

**Status.**
- `tofu fmt` and `tofu validate` run in CI for all four modules, with no credentials and no
  backend.
- None has been applied to a real account yet: that needs each cloud's credentials and the owner's
  go-ahead.
- The backlog asks for one non-DigitalOcean module to be applied before the first customer on that
  cloud.
