# ADR 0010: Model gateway with model profiles

Status: Accepted (2026-11-07)

## Decision

All LLM, embedding and reranker calls go through model-gateway using named profiles (cloud frontier: OpenAI/Anthropic/Gemini; on-prem: vLLM with Qwen models). Embeddings are 1024-d for both profiles. Routing can follow data classification.

## Why

Provider-agnostic, hybrid routing, budgets and redaction in one place.

## Consequences

- Default models chosen by the M-07 bake-off, not by public rankings.
