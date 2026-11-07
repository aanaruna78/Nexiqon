# model-gateway

LLM, embedding and reranker providers with routing, budgets and redaction. Plane: **data**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_model_gateway.main:create_app`
* Served under `/model-gateway` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_model_gateway/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/model-gateway
uv run nexiqon-run --services model-gateway
```
