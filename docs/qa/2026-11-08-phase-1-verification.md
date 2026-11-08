# Phase 1 verification — 8 November 2026

Verdict: existing automated suites pass locally, but full acceptance is withheld. Two additional identity edge cases reproduce defects, GitHub CI is not green, and a fresh container build is blocked by local tooling. Application code was not changed.

## Scope and environment

- Tested checkout: `phase-1/studio-shell`, commit `a67958a`, initially clean.
- Local branch ancestry is in the requested order: `main` (`b33ea45`) → identity (`edf838f`) → config (`2a4b266`) → events/audit (`baa0da1`) → Studio (`a67958a`). No branches were merged or pushed.
- Python 3.12.15, Node 22.22.1, pnpm 12.15.0, Docker Engine 29.1.3.
- Integration fixtures started real disposable Postgres, NATS and OPA containers; Temporal tests used the SDK's time-skipping test server.
- Gateway and browser tests used the already-running development stack and Studio on port 3100. Their running artifacts were not rebuilt from this checkout; these passes are not proof of a fresh deployment of this commit.
- Tests created fresh development tenants, config objects, invites, audit events and keys. The extra expiry probe's key was revoked. Test tenants remain in the development database, as the existing suites do not clean them up.

## Executed checks

| Check | Result |
| --- | --- |
| `uv sync --all-packages --frozen` | Pass; 147 packages checked |
| Frontend `install --frozen-lockfile` | Pass |
| `make lint typecheck arch contracts-check` | Pass; 231 Python files formatted, 137 source files type checked, zero architecture violations |
| `uv run pytest --junitxml=/tmp/nexiqon-qa-pytest.xml` | **208 passed**, no skips, 3 deprecation warnings; 47.83 seconds |
| OPA 0.70.0 `test /policies -v` | **9 passed** |
| `make fe-lint fe-test fe-build` | Pass; **16 Studio + 3 widget unit tests**, Studio and widget production builds |
| Studio `build-storybook` | Pass; bundler directive warnings |
| Frontend `generate`, then diff generated client files | Pass; no tracked differences |
| Studio `e2e` | **13 passed**, 14.8 seconds; includes axe scans and Arabic RTL |
| `uv run python tools/dev/smoke_gateway.py` | **23 checks passed**, not 25 |
| Production Python dependency export + `pip-audit --strict` | Pass; no known vulnerabilities reported |
| Extra identity expiry/date probes | **Two defects**, below |
| Fresh `docker build -f deploy/docker/Dockerfile -t nexiqon/platform:qa .` | Blocked at `RUN --mount`: local Docker lacks BuildKit/buildx |

The dependency audit covers the exported production Python dependencies. Gitleaks, Trivy filesystem/image scans, frontend dependency auditing, breaking-contract comparison, and a fresh-image smoke test were not verified locally. Accessibility passes apply to the screens and serious/critical violation threshold in the existing browser suite; they do not establish complete WCAG compliance or mobile usability.

## Reproduced defects

### QA-01 — Expired API keys remain usable from the context cache (P1)

Source: `services/identity/src/nexiqon_identity/access.py:256` and `:266`.

1. Authenticate through the development Keycloak realm and create a fresh tenant.
2. Create a server API key with `expires_at = now(UTC) + 4 seconds`.
3. Immediately request `GET /identity/v1/tenant` with the key: **200**. This populates the context cache.
4. Wait 5 seconds and repeat the identical request: **200**, although the key has expired. Expected: **401**.
5. Repeat with `Origin: https://qa.example` to use another cache entry: **401**. Server keys permit this origin; the changed outcome demonstrates the cached authentication result.

The API-key cache TTL always uses `cache_seconds` (30 in the development stack), without capping it at the key's expiry. The IdP-token path already caps its cache TTL against expiry. Cap the API-key TTL against `expires_at` and add a regression test with caching enabled. Identity integration fixtures currently set `context_cache_seconds=0`, so existing endpoint tests do not exercise this behavior.

### QA-02 — A timezone-free expiry value causes HTTP 500 (P2)

Source: `services/identity/src/nexiqon_identity/api.py:613`; request model at `:539`.

With valid owner credentials and tenant selection, send:

```http
POST /identity/v1/api-keys
Content-Type: application/json

{"name":"QA naive date","kind":"server","expires_at":"2099-01-01T00:00:00"}
```

Observed: **500**, `code=internal_error`. Expected: a validation **4xx** for a missing timezone, or an explicitly documented normalization policy. Pydantic accepts a naive datetime and the handler compares it with aware `datetime.now(UTC)`. Require an aware datetime or validate/normalize before comparing. Add a regression test.

## Claim verification and corrections

- Present: all five plan documents, 22 Mermaid sources with 22 SVGs, 16 ADRs, the v1.2 Markdown design addendum, 15 services, six deployment groups plus gateway, and nine config schemas. The backlog has **139 ID-labelled table rows** by the `PREFIX-number` convention; “about 150” is approximate.
- The 23-week pilot and tentative week-16 preview are documented targets, not delivery outcomes validated by tests.
- ADR 0016 was added after `main`; the claim that all 16 ADRs are already on `main` is inaccurate. The addendum found is Markdown; this review did not establish that an external design PDF was updated.
- Phase 1 functionality has meaningful integration coverage for identity, permissions, config lifecycle/resolution/snapshots, audit, event delivery and workflow data isolation. The route harness checks missing/forged context across services; it does not by itself prove data-level tenant isolation for every endpoint.
- Login was exercised with Keycloak. Clerk/Auth0 source and adapter tests are present, but live sign-in against those external providers was not tested. Local admin MFA is explicitly disabled in `deploy/compose/config/dev.yaml`; the browser pass does not prove a live admin-MFA flow.
- Studio's later design commits do not change its package manifest or pnpm lockfile relative to slice 4. Current production CSS totals **21,329 gzip bytes** when gzipped together (about 20.8 KiB), rather than 19 KB. Individual CSS chunks total 21,309 gzip bytes in this build.
- `make dev-up PROFILES=platform,apps,observability` does **not** start Studio: Compose has no Studio service. Start Studio separately as described in its E2E README. Grafana is included through the observability profile.
- The listed open items remain open: no `make seed`, no Groups screen, no browser E2E step in CI; gateway limits/CORS, denied-permission audit recording, native Clerk UI, generated Python clients and production deployment hardening were not accepted as completed.
- Phone layout quality, competitor trials, usability sessions, IP review, production cloud/hybrid/on-prem deployment, and the two policy decisions were not validated by the automated runs. These results do not close them.

## GitHub verification

The public GitHub API returned one workflow run when queried (latest eight requested): [CI run 42383786753](https://github.com/aanaruna78/Nexiqon/actions/runs/42383786753), for `main` at `b33ea45e3792f0c3589123a1ecaf88f990ce90ee`. Overall conclusion: **failure**.

- Python: success.
- Frontend: success.
- Security: failure at **Set up job**.
- Container image: failure at **Set up job**.
- Breaking contracts: skipped (push run).

This establishes a failed main run, not an application-level scan/build failure, and provides no green CI evidence for Phase 1. Setup failure details were not retrieved. The repository metadata reports `private=false`, confirming that tracked planning documents are publicly accessible. No visibility settings were changed.

## Evidence and acceptance

Raw local outputs, JUnit XML, extra probe results and the GitHub job summary are preserved in [evidence/2026-11-08](evidence/2026-11-08/). Files retain their `nexiqon-qa-*` names. No credentials or API-key secrets are printed in these artifacts.

Before acceptance: fix and retest QA-01 and QA-02, obtain green CI on the Phase 1 result, and build/smoke-test a fresh image with BuildKit available. Correct the local startup instructions and verification counts. Merge and deployment actions remain unperformed.
