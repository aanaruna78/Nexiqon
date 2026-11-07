# ADR 0005: PostgreSQL + pgvector with forced RLS; schema per service

Status: Accepted (2026-11-07)

## Decision

PostgreSQL 16 with pgvector and FTS. Each service owns its schema and role. Tenant tables use nexiqon_core.db.rls_policy_sql (ENABLE + FORCE RLS, policy on app.tenant_id). Apps connect as non-owner roles; TenantSessionFactory sets app.tenant_id transaction-locally.

## Why

One store for metadata, vectors and keyword search; database-enforced isolation as a second line of defence.

## Consequences

- Integration tests prove cross-tenant reads/writes fail and settings don't leak through the pool.
- Moving a service to its own cluster later needs no code change.
