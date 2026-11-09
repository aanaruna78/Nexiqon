# model-gateway

One entry point for chat, embeddings and reranking across OpenAI, Anthropic, Gemini and
self-hosted OpenAI-compatible servers (vLLM, Ollama). Plane: **data**. Served under `/model-gateway`.

| Endpoint | Permission | Notes |
|---|---|---|
| `POST /v1/chat` | `model.inference.run` | Tools, JSON-schema output, classification, conversation id |
| `POST /v1/embeddings` | `model.inference.run` | Always 1024 dimensions; never routed or failed over |
| `POST /v1/rerank` | `model.inference.run` | Profiles with a reranker enabled |
| `GET /v1/usage?month=YYYY-MM` | `model.usage.read` | Tokens and estimated cost by profile and model |

For every call the gateway:

1. **Resolves the model profile** from config (`/v1/resolve/profiles/model_profile/{name}`) with the
   caller's context token. Config applies security floors, so a profile that breaks a floor is
   refused (409) before any provider is called. The environment is set by the operator
   (`profile_environment`), never by the caller.
2. **Routes by data classification** using the profile's `routing` rules (at most 3 hops, loops
   refused). Classifications in `cloud_forbidden_classifications` (default: `restricted`) never
   reach a cloud profile (403). On-prem profiles may only use `openai_compatible` providers.
3. **Enforces budgets**: `budgets.monthly_usd` per profile and `budgets.per_conversation_tokens`
   (429 `budget_exceeded`).
4. **Redacts personal data** (emails, phone numbers, Luhn-valid card numbers) for cloud profiles
   unless `redact_pii: false`, and restores placeholders in the answer and tool arguments.
5. **Falls back** to `fallback_profile` on timeouts, 429 and 5xx (chat only; the fallback is also
   checked). Other failures return 502 without echoing the provider's response body.
6. **Records usage** (`usage_records`, no prompt or completion text) and emits
   `nexiqon.model-gateway.usage.recorded` through the outbox.

**Offline development provider.** With `allow_offline_provider: true` (the local stack sets it), the
`offline` provider serves the built-in `dev-offline` profile: hash embeddings, a lexical reranker and an
extractive "answer" that quotes the best-matching source sentence. It is **not a language model**. It
exists so the whole platform runs end to end without keys or GPUs, and it is refused unless enabled.

Provider keys: `NEXIQON_PROVIDERS__OPENAI_API_KEY`, `..._ANTHROPIC_API_KEY`, `..._GEMINI_API_KEY`,
`..._OPENAI_COMPATIBLE_API_KEY` (from OpenBao in production). Prices in
`defaults/prices.yaml` are illustrative; verify them before using costs for billing.

```bash
uv run pytest services/model-gateway
uv run nexiqon-run --services model-gateway
```
