# authz

Policy decisions (OPA) for role, resource and action authorization. Plane: **control**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_authz.main:create_app`
* Served under `/authz` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_authz/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/authz
uv run nexiqon-run --services authz
```
