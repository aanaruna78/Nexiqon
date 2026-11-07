# notification

Email, webhook and in-app notifications. Plane: **control**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_notification.main:create_app`
* Served under `/notification` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_notification/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/notification
uv run nexiqon-run --services notification
```
