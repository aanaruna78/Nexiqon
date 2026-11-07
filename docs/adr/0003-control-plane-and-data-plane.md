# ADR 0003: Control plane and data plane

Status: Accepted (2026-11-07)

## Decision

Services are assigned to a control plane (identity, authz, config, audit, evaluation, metering, governance, notification) or a data plane (channel, conversation, agent-runtime, retrieval, ingestion, tool-gateway, model-gateway).

## Why

Enables hybrid deployments where customer data never leaves the customer's data plane (ARCHITECTURE §7).

## Consequences

- Data plane must run from config snapshots if the control plane is unreachable (CF-05).
- Customer content never flows through the control plane (DV-08).
