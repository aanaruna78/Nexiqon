# conversation

Sessions, messages, provenance, feedback and escalations. Plane: **data**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_conversation.main:create_app`
* Served under `/conversation` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_conversation/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/conversation
uv run nexiqon-run --services conversation
```
