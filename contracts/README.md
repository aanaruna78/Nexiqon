# Contracts

Contract-first (PLAN.md §6, rule 1): a contract change is reviewed before the implementation.

| Folder | Format | Produced by |
|---|---|---|
| `openapi/` | OpenAPI 3.1, one file per service | `make contracts` (exported from each service's FastAPI app); CI fails if stale; oasdiff flags breaking changes vs `main` |
| `asyncapi/` | AsyncAPI 3 + CloudEvents envelope | Written by hand per event type (from Phase 1, EV-01) |
| `schemas/` | JSON Schema 2020-12 | Config object types: Domain Pack, agent, graph, tool, model profile (from Phase 1, CF-01/CF-04) |

TypeScript types for Studio and the widget are generated from `openapi/` into `frontend/packages/client`
(`pnpm --filter @nexiqon/client generate`). Typed Python clients are generated when the first real
service-to-service call lands in Phase 1.
