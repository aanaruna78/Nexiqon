# audit

Append-only, hash-chained audit log. Plane: **control**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_audit.main:create_app`
* Served under `/audit` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_audit/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/audit
uv run nexiqon-run --services audit
```
