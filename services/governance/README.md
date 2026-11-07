# governance

Retention, tenant deletion/export sagas and data-subject requests. Plane: **control**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_governance.main:create_app`
* Served under `/governance` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_governance/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/governance
uv run nexiqon-run --services governance
```
