# ADR 0004: Ports and adapters for every external dependency

Status: Accepted (2026-11-07)

## Decision

Each external dependency (DB, vector store, storage, events, secrets, models, IdP, workflows, observability) is accessed through a port with swappable adapters. Vendor SDKs may only be imported in an `adapters` package, enforced by tools/lint/check_architecture.py.

## Why

Cloud-agnostic, on-prem and hybrid support without forks.

## Consequences

- Adding a provider = new adapter + contract tests.
- Lint failures block CI.
