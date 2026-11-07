# ADR 0002: Microservices packaged as deployment groups

Status: Accepted (2026-11-07)

## Decision

15 Python services plus the edge gateway, split along bounded contexts (ARCHITECTURE §1). For the MVP they run as 6 Python deployment groups plus edge, defined in deploy/groups.yaml. Every service is always served under /<service>; splitting a group changes only the host (Topology.url_for).

## Why

The team is small (REVIEW F1). Groups cut operational load roughly in half while preserving service boundaries, contracts and data ownership.

## Consequences

- One container image; NEXIQON_GROUP selects the group (nexiqon-run).
- Services must never import another service's package; they talk over HTTP/events.
- Splitting is a config change: NEXIQON_TOPOLOGY_MODE=split or edit groups.yaml.
