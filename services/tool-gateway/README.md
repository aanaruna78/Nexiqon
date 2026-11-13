# tool-gateway

How assistants act on business systems. Plane: **data**; its own group. See ADR 0019.

| Endpoint | Purpose |
|---|---|
| `GET /v1/tools/{name}` | Public definition: description, input schema, risk (no URLs or credentials) |
| `POST /v1/tools/{name}/invoke` | Run a tool as the caller (`agent`, `arguments`, `idempotency_key`, `approval_id`) |
| `POST /v1/tools/{name}/approvals` · `POST /v1/approvals/{id}/decision` | Confirm a write; decide human tasks |
| `GET /v1/approvals` · `GET /v1/calls` | Approvals log and call log (no arguments or results in the call log) |
| `POST /v1/tools/{name}/dry-run` | Validate arguments and preview the request; nothing is sent |
| `PUT/GET/DELETE /v1/credentials[/{name}]` | Write-only workspace credentials (OpenBao) |
| `POST /v1/openapi/import` | Tool definitions from an OpenAPI 3 document |

Tool definitions (`tool` config objects) declare the request (`url_template` with `{argument}` and
`{caller.actor_id}` placeholders, `host_allowlist`, `auth`), `credential_ref: secret://<name>`,
`input_schema`, `output_schema` (results are minimised to it), `risk_level`, `rate_limit_per_minute`,
`timeout_ms` and `result_classification`.

Development: `mock_apis.py` serves demo APIs (account/plan lookup, support cases) for two datasets
(`demo-token-acme`, `demo-token-globex`); the dev stack runs it as `mock-apis` on port 9000.
