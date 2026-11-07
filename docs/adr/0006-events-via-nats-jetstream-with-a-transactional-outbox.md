# ADR 0006: Events via NATS JetStream with a transactional outbox

Status: Accepted (2026-11-07)

## Decision

Business writes stage CloudEvents in an outbox table in the same transaction (nexiqon_core.events.add_event); OutboxRelay publishes them. Consumers are idempotent.

## Why

No lost or phantom events; lightweight, cloud-agnostic bus that runs on-prem.

## Consequences

- Event types: nexiqon.<service>.<noun>.<verb>; envelope schema in contracts/asyncapi.
- Kafka adapter possible later behind the EventPublisher port.
