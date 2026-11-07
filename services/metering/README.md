# metering

Usage, cost, quotas, analytics and content-gap insights. Plane: **control**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_metering.main:create_app`
* Served under `/metering` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_metering/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/metering
uv run nexiqon-run --services metering
```
