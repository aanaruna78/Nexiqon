# ADR 0017: Per-service identities for background work, and the knowledge pipeline split

Status: Accepted (2026-11-08)

## Decision

- **Service tokens.** A workflow acting for a tenant (e.g. ingestion embedding a document) has no user
  token. A data-plane service holds its own signing key and mints short-lived tenant-context tokens for
  itself. Verifiers map that key id to the service (`context_token.service_keys`). A token signed with it is
  accepted only if actor, actor type and roles are exactly `service:<name>`. Identity-issued tokens may
  never carry a `service:` role. OPA grants each service role a short list, and actions in `service_only`
  (index writes) also require a service actor.
- **Ingestion owns sources, files and lifecycle; retrieval owns the index.** Ingestion stores collections,
  sources, documents and runs, plus raw files in object storage. It writes each document's whole tree to
  retrieval's index API in one atomic replace (`PUT /v1/index/documents/{id}`). A stale version is refused.
- **Pipeline on Temporal.** The pipeline is sync/ingest/reindex workflows built from idempotent activities:
  discover, fetch, scan, process (parse, chunk, embed, index) and finish. Permanent problems mark the
  document `failed` with an `error_code`. They do not fail the run.
- **Plugins.** Connectors, parsers and chunkers implement the `nexiqon-sdk` ports. They declare a manifest
  with a JSON Schema for their configuration, and are discovered through the `nexiqon.plugins` entry point.
  The built-in plugins load the same way.
- **One vector space per collection.** Embeddings never fall back or route to another model. A
  model-profile change triggers a reindex, and every node records its `embedding_model`.

## Why

A shared "service" super-role would let one compromised service act as any other. Per-service keys limit
the blast radius to what that service can already do. Keeping the index in retrieval keeps each schema
owned by one service. The atomic replace makes "old or deleted content is unretrievable" (IN-07) a
database property.

## Consequences

- Each service identity is a key pair to provision and rotate (dev: `make dev-secrets`).
- Connector secrets (S3 keys, Git tokens) are operator-provisioned per tenant (`connector_credentials`,
  OpenBao in production). Tenants reference them by name and never send them through the API. A
  self-service secret store is a follow-up.
- While a reindex runs, documents not yet reprocessed still carry the old model. Search (slice 3)
  filters by the collection's current embedding model, so they are briefly missing, never wrong.
