# ADR 0011: Domain Packs and layered configuration

Status: Accepted (2026-11-07)

## Decision

Domain behaviour (vocabulary, intents, graphs, prompts, tools, guardrails, evals) lives in versioned Domain Packs. Config resolves platform → deployment → region → tenant → pack → agent → channel → environment, with security floors. Core code contains no domain words (lint-enforced).

## Why

Any domain without code changes; the Customer Support pack proves it (R-02).

## Consequences

- Service settings already layer YAML files (NEXIQON_CONFIG_FILES) under env vars.
