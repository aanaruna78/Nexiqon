# Private (Kubernetes)

Run everything in your own cluster with the Helm chart, `deploy/helm/nexiqon`. The chart is the same
for every cloud. Managed databases, buckets and keys are referenced by name, as existing Secrets.

## Profiles

| Profile | For |
|---|---|
| `values/private.yaml` | A standard private install: two replicas per group, your SMTP relay, no cloud model keys |
| `values/minimal.yaml` | The smallest footprint: one CPU node and one GPU node ([sizing](../../guides/minimal-footprint.md)) |
| `values/hybrid-data.yaml` | The data plane of a [hybrid](hybrid.md) install |

```bash
helm install nexiqon deploy/helm/nexiqon -f deploy/helm/nexiqon/values/private.yaml \
  --set studio.baseUrl=https://ai.example.com \
  --set studio.oidc.issuer=https://login.example.com/realms/corp
```

**Before installing**, create these Secrets:

- `nexiqon-database` (`url`, `migrationUrl`);
- `nexiqon-keys`, made with `nexiqon-keys` from the platform image;
- `nexiqon-studio`;
- optionally `nexiqon-blobs`, `nexiqon-openbao` and `nexiqon-smtp`.

The chart then:

- runs the database migrations before every install and upgrade;
- applies default-deny network policies;
- runs every container as non-root, with read-only filesystems.

**Self-hosted models.** Set `models.enabled=true` to run the vLLM servers on nodes labelled
`nexiqon.dev/pool: gpu` ([GPU models](../../guides/gpu-models.md)).

## Cloud infrastructure (OpenTofu)

--8<-- "deploy/tofu/README.md:3"
