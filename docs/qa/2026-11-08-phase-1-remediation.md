# Phase 1 remediation: response to the 8 November 2026 verification

Responds to [2026-11-08-phase-1-verification.md](2026-11-08-phase-1-verification.md). Branch `phase-1/qa-fixes`
(on top of `phase-1/studio-shell`). Every finding was re-verified against code before fixing.

| Finding | Verified | Fix | Evidence |
|---|---|---|---|
| **QA-01** expired API key usable from the context cache (P1) | Yes: `resolve_api_key` returned `cache_seconds` regardless of `expires_at`; the IdP path already capped its TTL | TTL capped at the key's remaining lifetime (`access.py`) | Regression test with caching on (`test_qa01_expired_key_is_refused_even_when_cached`), shown to **fail on the old code** and pass now; plus `test_qa01_unexpiring_key_is_still_cached`; gateway smoke probe through the real 30 s cache |
| **QA-02** timezone-free `expires_at` → 500 (P2) | Yes: naive vs aware comparison raised `TypeError` | `expires_at` is `AwareDatetime`: naive values get **422 validation_failed** | Regression test (naive 422, past 400, aware 201), fails on old code; gateway smoke probe |
| GitHub CI red (Security, Container image fail at *Set up job*) | Yes: `aquasecurity/trivy-action@0.28.0` does not exist (tags are now `v`-prefixed; `v0.28.0` resolves) | Tag corrected in both jobs; CI now also runs on every branch push, so phase branches get green evidence before merge | CI run on `phase-1/qa-fixes` (see below) |
| Fresh image build blocked without BuildKit | Yes: `RUN --mount` needs BuildKit; local Docker has no buildx | Dockerfile builds with any builder (no cache mount; CI still caches layers) | `docker build -f deploy/docker/Dockerfile` succeeds; container serves `/healthz`, `/identity/meta` as uid 10001; full stack rebuilt from this checkout passes the gateway smoke test |
| Smoke test "25 checks" | Correct: there were 23 | Two QA probes added: **26** checks now | Smoke run on the rebuilt stack |
| "All 16 ADRs on main" | Correct: ADR 0016 is on the Phase 1 branches | Statement corrected; it reaches `main` with the merge | — |
| CSS "19 KB" | Correct: measured before the sidebar commit; ~20.8 KiB gzip at `a67958a` | Corrected figure | — |
| `make dev-up` does not start Studio | Correct | New `make studio` target; README says Studio runs separately | — |
| Open items (seed, Groups UI, E2E in CI, gateway limits/CORS, denied-decision audit, Clerk UI, Python clients, prod hardening, usability, policy decisions) | Agreed: still open | Tracked; not claimed complete | — |

## Re-run after fixes

| Check | Result |
|---|---|
| Lint, format, strict mypy (137 files), architecture rules | Pass |
| Contracts export + generated TS types | No changes |
| `pytest` (real Postgres, NATS, OPA, Temporal) | **211 passed** (208 + 3 regressions) |
| Gateway smoke on a stack rebuilt from this checkout | **26 checks passed**, including both QA probes |
| Studio E2E with axe (EN + AR) | **13 passed** |
| Fresh `docker build` without BuildKit + container smoke | Pass |

Not re-verified here: live Clerk/Auth0 sign-in, live admin-MFA flow, and full WCAG/mobile usability (unchanged from the report).
