# config

Config registry: domain packs, agents, graphs, tools, model profiles, versions. Plane: **control**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_config.main:create_app`
* Served under `/config` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_config/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/config
uv run nexiqon-run --services config
```
