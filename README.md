# Nexiqon by ThinkHiveLabs

Secure, configurable, domain-agnostic enterprise agentic AI platform: grounded answers with citations,
controlled tools, tenant isolation, evaluation and governance. It runs as shared SaaS, dedicated, hybrid or
private, from one codebase.

**Status:** Phase 0 (platform setup). See [docs/plan/PLAN.md](docs/plan/PLAN.md).

## Repository layout

| Path | What |
|---|---|
| `libs/nexiqon-core` | Service chassis: layered settings, tenant-context tokens, RLS sessions, error envelope, logging, telemetry, outbox, deployment-group runner, test kit |
| `services/*` | 15 services (generated from `templates/service`), each served under `/<service>` |
| `deploy/groups.yaml` | How services are packaged into deployment groups |
| `deploy/docker`, `deploy/compose` | Platform image and local dev stack |
| `contracts/` | OpenAPI (exported), AsyncAPI/CloudEvents, config JSON Schemas |
| `frontend/` | pnpm workspace: Studio (Next.js), widget (Lit), generated API types |
| `templates/service` | Copier template for new services |
| `tools/` | Architecture lint, contract export |
| `docs/` | Plan, architecture, UX, ADRs, diagrams, design addendum |

## Quick start

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 22.

```bash
make setup                         # Python + frontend deps, git hooks
make check                         # what CI runs
make dev-up                        # Postgres+pgvector, Valkey, NATS, S3 storage (+ local signing keys)
make dev-up PROFILES=platform,apps # + Temporal, Keycloak, OpenBao, OPA, migrations, gateway, 6 groups
uv run python tools/dev/smoke_gateway.py   # end-to-end check through the gateway
make dev-down
```

With `observability` in `PROFILES`, Grafana (`localhost:3000`, admin/admin) shows traces (Tempo), metrics
and the **Nexiqon services** dashboard; every request is traced from the gateway through services and
events. Feature flags are served by flagd from `deploy/compose/flags/flags.json`.

The gateway listens on `localhost:8000` and routes `/<service>/...` to the right group. Requests carry
`Authorization: Bearer <IdP token or nxq_ API key>` and, for users in several tenants,
`X-Nexiqon-Tenant: <slug or id>`. The dev Keycloak realm (`localhost:8080`, realm `nexiqon`) has a user
`dev` / `dev-password`.

| Group | Local port | Services |
|---|---|---|
| control-core | 8101 | identity, authz, config, audit |
| control-ops | 8102 | evaluation, metering, governance, notification |
| knowledge | 8103 | ingestion, retrieval |
| agent | 8104 | agent-runtime, conversation, channel |
| tool-gateway | 8105 | tool-gateway |
| model-gateway | 8106 | model-gateway |

## Engineering rules

Contract first · every service from the template · no vendor SDK outside adapters · no domain words in core
code · policy before model · the isolation suite grows with every endpoint · no feature without UX.
Details: [PLAN.md §6](docs/plan/PLAN.md) and [ADRs](docs/adr/README.md).

Add a service: `make new-service NAME=<kebab-name> PLANE=<control|data>`.

Domain Packs live in `packs/<name>/pack.yaml` (format: `docs/plan/ARCHITECTURE.md` §6.2, schema:
`contracts/schemas/config/domain_pack.schema.json`). Validate with
`uv run python -m tools.packs.apply --tenant x --token y --validate-only`; apply to a tenant with
`--tenant <slug> --token <IdP token> --publish --deploy dev`.
