# Nexiqon Helm chart (DV-02)

One chart for every install: SaaS, private (on-premises) and evaluation clusters. Nothing
cloud-specific lives in it. Managed databases, buckets and keys are referenced by name, so the same
chart runs on DigitalOcean, AWS, GCP, Azure or bare metal.

| Part | What runs |
|---|---|
| Workloads | One Deployment per group in `deploy/groups.yaml` (`topology.mode: grouped`), or one per service (`split`). Moving a service between groups is values only. Each workload mounts only its group's keys: a service's own signing key never reaches another group. |
| Migrations | A Job runs every service's migrations once: pre-install and pre-upgrade, or post-install with bundled databases. |
| Gateway | Envoy, configured from the groups. It removes client-sent context and diagnostics headers, asks identity to authorise each request, never routes internal services, and allows CORS for the widget routes and long streams for answers. Optional Ingress. |
| OPA, flagd | Authorization policies (`files/policies`, synced from `services/authz`) and feature flags. |
| Studio | The admin app. It also serves the widget bundle at `/widget/nexiqon-chat.js` (`deploy/docker/studio.Dockerfile`). |
| Bundled | `bundled.enabled`: single-replica PostgreSQL (pgvector), Valkey, NATS, SeaweedFS, Temporal, Keycloak and OpenBao for evaluation only. |

Pods run as a non-root user with a read-only root filesystem, no privilege escalation, all
capabilities dropped and no service account token. Groups with more than one replica get a
PodDisruptionBudget.

## Secrets (never created by the chart outside evaluation mode)

| Secret | Keys |
|---|---|
| `nexiqon-database` | `url` (application role), `migrationUrl` (owner role) |
| `nexiqon-keys` | `secrets.yaml`, `service-keys.yaml`, `identity-<service>.yaml` |
| `nexiqon-studio` | `STUDIO_SESSION_SECRET`, optional `OIDC_CLIENT_SECRET` |
| `nexiqon-blobs` | `access_key`, `secret_key` (S3-compatible storage) |
| `nexiqon-openbao` | `token` (tool credentials) |
| `nexiqon-providers` | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (all optional) |

Production clusters get these from OpenBao or External Secrets. For evaluation,
`tools/dev/k8s_secrets.py` makes `nexiqon-keys` and `nexiqon-studio` from the local development
keys.

## Profiles

- `values/kind.yaml`: a local kind cluster with bundled dependencies, offline models and demo APIs.
  `uv run python tools/dev/kind_up.py` builds and loads the images, creates the Secrets and
  installs the chart (needs docker, kind, kubectl and helm).
- `values/saas.yaml`: production SaaS with managed services from `deploy/tofu` and an ingress.
- `values/private.yaml`: private installs on self-hosted models (`docs/guides/gpu-models.md`).

## Checks

CI lints the chart and renders every profile in both topologies. It validates the manifests
against Kubernetes 1.31 schemas (kubeconform) and runs Envoy's validator on the generated gateway
configuration. `tools/lint/test_helm_chart.py` keeps the chart's groups and copied files in step
with the repository.
