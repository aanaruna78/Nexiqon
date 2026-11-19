# Minimum on-premises footprint (DV-09)

The smallest supported Kubernetes install is **one CPU node and one GPU node**
(`deploy/helm/nexiqon/values/minimal.yaml`). For one server without Kubernetes, use
`deploy/single-node` instead.

## What runs where

| Node | Workloads | Requests (from the rendered chart) |
|---|---|---|
| **CPU:** 8 vCPU, 32 GB, 200 GB SSD | 6 platform groups, gateway, Studio, OPA and flagd at one replica each | 1.2 CPU, 2.5 GiB |
| | PostgreSQL 16 with pgvector, NATS JetStream, Temporal, S3-compatible storage and OpenBao, from their own charts (settings below) | about 2 CPU, 6 GiB |
| **GPU:** 1 × 48 GB (L40S), or 1 × 24 GB (L4) with the smaller chat model | vLLM chat (Qwen3-8B AWQ), embeddings and reranking (Qwen3 0.6B) | 3 × 1 GPU (time-sliced), about 40 GiB memory |

That leaves the CPU node about half free, for ingestion bursts and the operating system.

## The dependencies at their smallest

| Dependency | Chart and settings |
|---|---|
| PostgreSQL 16 + pgvector | One instance, 2 CPU / 4 GiB, 100 GiB volume, `shared_buffers=1GB`. Daily backups (chart `backup.enabled`, on in this profile) copied off the cluster |
| NATS | JetStream, one server, 1 GiB file storage |
| Temporal | `temporalio/auto-setup` against the same PostgreSQL, one replica |
| Object storage | SeaweedFS or MinIO, one server, versioning on |
| OpenBao | One server, file or integrated storage, with auto-unseal where an HSM or KMS exists |

Point the chart at them with the usual Secrets: `nexiqon-database`, `nexiqon-blobs`,
`nexiqon-openbao` (`deploy/helm/nexiqon/values.yaml`).

## Left out, on purpose

- **A service mesh (Linkerd).** Traffic between pods is limited by the chart's default-deny
  NetworkPolicies, and service calls carry signed tokens. Add Linkerd only if your policy
  requires mTLS between pods: it costs about 0.2 CPU and 300 MiB per node.
- **A bundled monitoring stack (LGTM).** Traces and metrics go over OTLP to your collector
  (`extraEnv` in the profile). The alert rules (`deploy/observability/prometheus-rules.yaml`)
  load into any Prometheus.
- **LLM tracing tools (Langfuse).** The Answer Inspector and evaluations cover answer quality
  inside the product.

## One GPU for three model servers

Each vLLM server asks for `nvidia.com/gpu: 1`. On a node with one GPU, configure the NVIDIA device
plugin's time-slicing with at least 3 replicas. The servers' `--gpu-memory-utilization` values
(0.80 + 0.08 + 0.08) keep them within one card's memory.

With a 24 GB card, use a 4B chat model: set `models.servers.vllm.args` to
`--model=Qwen/Qwen3-4B-AWQ` and `--max-model-len=16384`.

## What grows first

| Load | Add |
|---|---|
| More concurrent answers (above about 20 per minute) | A second GPU, or a larger card for the chat model; then `agent` replicas |
| Large document imports | `knowledge` replicas and PostgreSQL memory |
| Many staff in Studio | `studio` and `control-core` replicas |
| High availability | Go to the standard profile (`values/private.yaml`): 2+ replicas, three CPU nodes, a PostgreSQL standby |

## Proof

CI renders this profile and validates every resource against the Kubernetes 1.31 schemas.

Running it on real nodes, with the customer's or a lab GPU, is the acceptance step before the
first on-premises customer. It needs hardware we do not have in CI.
