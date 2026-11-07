# agent-runtime

Declarative LangGraph agent execution. Plane: **data**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_agent_runtime.main:create_app`
* Served under `/agent-runtime` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_agent_runtime/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/agent-runtime
uv run nexiqon-run --services agent-runtime
```
