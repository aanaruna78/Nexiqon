# ADR 0012: No graph database; hierarchical retrieval in Postgres

Status: Accepted (2026-11-07)

## Decision

pgvector HNSW already traverses a navigable graph. Structure is used for quality: document tree (ltree), small-to-big retrieval, section-path citations; summary nodes eval-gated; knowledge-graph port P2 with a Postgres adapter first.

## Why

Avoids a second store with weaker isolation, harder deletion and a heavier on-prem footprint.
