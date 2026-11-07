# ADR 0015: Python tooling and quality gates

Status: Accepted (2026-11-07)

## Decision

uv workspace (libs/*, services/*), Python 3.12, ruff (lint + format), mypy strict, pytest with testcontainers, Copier service template, contract export check, architecture lint, gitleaks, pip-audit, Trivy.

## Why

Fast, strict feedback from the first commit.

## Consequences

- make check runs what CI runs.
