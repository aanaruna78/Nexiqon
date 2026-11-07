# ADR 0008: OPA for authorization decisions

Status: Accepted (2026-11-07)

## Decision

The authz service evaluates OPA/Rego policies: decide(actor, action, resource, context). Deny by default. Security floors cannot be loosened by configuration.

## Why

Policy as versioned code, testable, separate from business logic and from the LLM.
