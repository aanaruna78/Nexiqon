# ADR 0013: Frontend stack

Status: Accepted (2026-11-07)

## Decision

pnpm workspace in frontend/: Next.js Studio (apps/studio), Lit Web Component widget (apps/widget), generated API types (packages/client, openapi-typescript).

## Why

Accessible component primitives, framework-agnostic widget, types generated from contracts.

## Consequences

- Design system (shadcn/ui + Radix) arrives in Phase 1 (UX-04/05).
