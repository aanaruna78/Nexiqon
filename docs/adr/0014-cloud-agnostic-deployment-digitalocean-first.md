# ADR 0014: Cloud-agnostic deployment, DigitalOcean first

Status: Accepted (2026-11-07)

## Decision

Kubernetes + Helm (umbrella chart, group values) and Docker Compose for dev/single node. DigitalOcean is the first reference cloud (DOKS, Managed PostgreSQL with pgvector, Managed Valkey, Spaces, GPU Droplets); OpenTofu modules for AWS/GCP/Azure use the same ports. Local S3-compatible storage is SeaweedFS (MinIO no longer publishes community images on Docker Hub).

## Why

Portability for SaaS, hybrid and private deployments.

## Consequences

- Nothing DigitalOcean-specific outside OpenTofu modules and Helm values.
