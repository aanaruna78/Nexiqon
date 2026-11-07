# retrieval

Hybrid search, ACL filtering, small-to-big expansion and citation verification. Plane: **data**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_retrieval.main:create_app`
* Served under `/retrieval` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_retrieval/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/retrieval
uv run nexiqon-run --services retrieval
```
