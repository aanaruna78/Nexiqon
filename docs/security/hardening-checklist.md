# Hardening checklist (S-02)

Every item is done and checked by a test, a CI job or a chart check, unless marked otherwise.

## Web

- [x] **Studio security headers:**
  - Content-Security-Policy (`default-src 'self'`, `connect-src 'self'`, `object-src 'none'`,
    `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`);
  - HSTS (2 years, production);
  - COOP same-origin;
  - X-Content-Type-Options, X-Frame-Options DENY;
  - Referrer-Policy, Permissions-Policy.

  Set in `frontend/apps/studio/next.config.ts` and checked by the e2e suite.
- [x] **Gateway responses:** `nosniff`, `DENY` framing, `no-referrer`, HSTS (SaaS and private
  profiles); the `server` header removed.
- [x] **Session cookies** are HttpOnly, Secure and SameSite. Tokens never reach the browser
  (Studio BFF, ADR 0016).
- [x] **The widget** renders text only, in Shadow DOM; links only `http(s)`, with
  `noopener noreferrer`.

## Network

- [x] **Default-deny NetworkPolicy:** pods take traffic only from the release. The gateway and
  Studio also take it from the ingress controller; monitoring is optional.
- [x] **No pod can reach the cloud metadata address** (`169.254.169.254`).
- [x] **A request ceiling per gateway pod** (Envoy local rate limit, `gateway.rateLimit`); per-key limits on tools; hard model budgets.
- [x] **Internal-only routes** (authz, model-gateway, `/identity/internal/*`) are never routed
  by the gateway.
- [x] **Outbound fetches** go through `SafeFetcher`: public addresses only, pinned DNS, size and
  time limits.

## Containers

- [x] **Non-root.** The platform runs as uid 10001; Studio as uid 10001.
- [x] **Locked down at runtime:** read-only root filesystem, all capabilities dropped, no
  privilege escalation, no service-account token.
- [x] **Platform image:** no pip, setuptools or wheel; no setuid binaries; current Debian security
  updates; started without a shell. Studio image: npm, npx and corepack removed.
- [x] **Trivy:** HIGH and CRITICAL fail the image job; CRITICAL fails the dependency scan.
- [x] **Signed images with SBOMs** (cosign keyless, CycloneDX). The publish job is ready; set the
  repository variable `PUBLISH_IMAGES=true` to switch it on.

## Data and secrets

- [x] **RLS (FORCE)** on every tenant table; the app role owns no tables.
- [x] **Secrets live outside the platform database.** Tool credentials are in OpenBao; signing
  keys are files mounted per group; webhook secrets and API key secrets are shown once (keys
  stored as hashes).
- [x] **Logs redact secrets and PII:** tokens, keys, emails, phone and card numbers
  (`nexiqon_core.logging.redact`).
- [x] **Events carry ids and counts only**; email addresses are stored hashed.

## Supply chain

- [x] **Dependencies pinned**, at least two weeks old; exceptions are recorded next to the pin.
- [x] **Lockfiles:** `uv.lock` and `pnpm-lock.yaml`, built `--frozen`.
- [x] **Third-party actions pinned:** Trivy by SHA; others by major version from verified
  publishers.
- [x] **Gitleaks** on every push, with a narrow allowlist (QA hash manifests).

## Operations

- [x] **Alerts with runbooks** (S-03), unit-tested with promtool in CI.
- [x] **Nightly backups** and a timed restore drill (G-03).
- [x] **Incident response** and post-incident template: `docs/runbooks/incidents.md`.
- [ ] **External penetration test before the pilot.** Planned for Phase 5, R-03.
