# ADR 0007: Temporal for long-running cross-service workflows

Status: Accepted (2026-11-07)

## Decision

Ingestion, reindexing, tenant deletion/export and evaluation runs are Temporal workflows.

## Why

Durable sagas with retries and visibility; self-hostable.

## Consequences

- Each service implements tenant.delete/tenant.export hooks (nexiqon_core.lifecycle); the template generates stubs.
