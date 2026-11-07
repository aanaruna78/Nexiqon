# ingestion

Source connectors, parsing, chunking, embedding and document lifecycle. Plane: **data**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_ingestion.main:create_app`
* Served under `/ingestion` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_ingestion/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/ingestion
uv run nexiqon-run --services ingestion
```
