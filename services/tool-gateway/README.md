# tool-gateway

Policy-controlled tool execution with secrets, egress allowlist and approvals. Plane: **data**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_tool_gateway.main:create_app`
* Served under `/tool-gateway` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_tool_gateway/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/tool-gateway
uv run nexiqon-run --services tool-gateway
```
