# Self-hosted models on GPUs (M-06)

Private and hybrid installs answer with models on the customer's own GPUs. Three vLLM servers
cover what the platform needs. The built-in `on-prem-small` and `on-prem-standard` model profiles
point at them, so assistants switch by choosing a profile; there is nothing to configure in
code.

| Endpoint | Purpose | Default model | GPU memory (approx.) |
|---|---|---|---|
| `vllm` | chat, tool calls, constrained JSON | Qwen3-8B (AWQ 4-bit) | 8–10 GB weights + KV cache |
| `vllm-embed` | embeddings (1024 dimensions) | Qwen3-Embedding-0.6B | ~1.5 GB |
| `vllm-rerank` | reranking | Qwen3-Reranker-0.6B | ~1.5 GB |

## Sizing

The **chat model** sets the size. The embedding and reranking models are small and can share a GPU
with it (`gpu-memory-utilization` splits the card).

| Profile | Chat model | Minimum | Comfortable (about 20 concurrent conversations) |
|---|---|---|---|
| `on-prem-small` | 8B, 4-bit | 1 × 24 GB (L4, A10G, RTX 4090) | 1 × 48 GB (L40S, A6000) |
| `on-prem-standard` | 30–35B mixture-of-experts, 4-bit | 1 × 48 GB | 1 × 80 GB (A100, H100) or 2 × 48 GB with tensor parallelism |

Rules of thumb:

- **KV cache.** It grows with context length times concurrent requests. At 32k context, budget
  roughly 0.15 GB per active conversation for an 8B model. Lower `VLLM_CHAT_CONTEXT` to fit more
  users on one card.
- **Embedding throughput.** Ingesting about 10,000 pages takes roughly 5–10 minutes on one shared
  L4. Search embeds one short query per question, which is negligible.
- **CPU and memory.** Plan 8 vCPU and 32 GB RAM per GPU node for vLLM and the model download.
- **Disk.** Budget 30 GB for the default weights in the `hf-cache` volume (more for larger chat
  models).

## Running it (Compose)

```bash
docker compose -f deploy/compose/docker-compose.yml -f deploy/compose/docker-compose.gpu.yml \
  --profile platform --profile apps --profile gpu up -d
```

Overrides (environment variables):

| Variable | Meaning |
|---|---|
| `VLLM_CHAT_MODEL` | Hugging Face repo of the chat model |
| `VLLM_CHAT_NAME` | Name it is served as; must match the model profile's `chat.model` |
| `VLLM_CHAT_CONTEXT` | Context window |
| `VLLM_CHAT_GPUS` | GPU ids for chat, e.g. `0,1` |
| `VLLM_SMALL_GPUS` | GPU for the embedding and reranking models |
| `HF_TOKEN` | Token for gated models |
| `HF_HUB_OFFLINE=1` | Use pre-loaded weights only (air-gapped) |

To use a different chat model, deploy a tenant `model_profile` whose `chat.model` matches
`VLLM_CHAT_NAME` and whose `capabilities` are accurate. Set `json_schema_output: false` for models
without reliable JSON; the gateway then uses vLLM's guided decoding instead.

## Checking it

1. `curl http://localhost:8000/health` from inside each container reports healthy.
2. In Studio, open **Models & data policy**: the on-prem profiles show "On your servers".
3. Create an assistant on `on-prem-small` and ask a question in the Test tab. The Answer
   Inspector shows the model as `qwen3-8b`.
4. Run the model comparison (M-07) on the gold set before choosing defaults:
   `uv run python -m tools.eval.model_bakeoff --profiles on-prem-small,on-prem-standard`.

## Status

The recipe and its configuration are validated. Running them on a target GPU is still to be done.
The Helm values for GPU node pools come with the Helm chart (DV-02).
