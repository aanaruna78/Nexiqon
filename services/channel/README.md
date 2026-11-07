# channel

Channel adapters (web widget, API) and session bootstrap. Plane: **data**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_channel.main:create_app`
* Served under `/channel` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_channel/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/channel
uv run nexiqon-run --services channel
```
