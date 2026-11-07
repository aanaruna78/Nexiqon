# identity

Tenants, users, memberships, IdP adapters and tenant-context tokens. Plane: **control**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_identity.main:create_app`
* Served under `/identity` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_identity/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/identity
uv run nexiqon-run --services identity
```
