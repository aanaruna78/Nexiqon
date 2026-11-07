# ADR 0009: Identity providers and the tenant-context token

Status: Accepted (2026-11-07)

## Decision

Clerk (hosted SaaS), Keycloak (on-prem, bundled) and Auth0/generic OIDC sit behind an identity port. After the gateway validates the IdP token, identity mints a short-lived, audience-scoped ES256 tenant-context token (X-Nexiqon-Context). Every service verifies it; tenant id is never taken from bodies, query strings or plain headers.

## Why

One trust model across providers and services.

## Consequences

- nexiqon_core.tenancy implements issuer/verifier; tests cover expiry, audience, forged keys and unsigned tokens.
