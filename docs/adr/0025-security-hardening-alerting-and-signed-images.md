# ADR 0025: Security hardening, alerting and signed images

Status: Accepted (2026-11-19)

## Context

Phase 4 closes with S-01 (threat model), S-02 (hardening), S-03 (runbooks and alerts) and DV-01
(hardened, signed images). Most controls already exist from earlier phases. This ADR records what
was added and what is accepted as residual risk.

## Decision

- **Threat model** (`docs/security/threat-model.md`):
  - STRIDE across the seven trust boundaries, and the OWASP Top 10 for LLM applications (2025);
  - each threat names its mitigation and the test or check that proves it;
  - the residual risks are listed, and the model is reviewed when a boundary changes.
- **Logs redact personal data and secrets.** A structlog processor masks:
  - values of keys that look like secrets;
  - emails, phone and card numbers, bearer tokens, JWTs and platform keys inside strings.

  Ids and timestamps stay readable. This is tested.
- **Headers:**
  - Studio sends a CSP (`default-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`,
    `object-src 'none'`, …), HSTS in production, and COOP;
  - the gateway adds `nosniff`, `DENY` framing, `no-referrer` and HSTS (SaaS and private
    profiles), and drops the `server` header;
  - an e2e test checks Studio's headers.
- **Network:**
  - a default-deny NetworkPolicy lets pods take traffic only from the release (the gateway and
    Studio also from the ingress controller, optionally monitoring);
  - egress may go anywhere except `169.254.169.254`, as defence in depth behind SSRF checks;
  - a request ceiling per gateway pod (Envoy local rate limit) sits on top of the tool limits and
    hard model budgets.
- **Images:**
  - **Platform:** Debian-slim (the Git connector needs git), with current security updates; no
    pip, setuptools or wheel; no setuid binaries; non-root; started without a shell (the runner
    reads `NEXIQON_GROUP`).
  - **Studio:** Alpine with npm removed.
  - CI fails on HIGH or CRITICAL findings in either image.
  - A publish job pushes both images to GHCR, signs them keyless with cosign (the workflow's OIDC
    identity), and attaches CycloneDX SBOMs. It is **off until `PUBLISH_IMAGES=true`** is set
    on the repository: publishing is the owner's decision.
- **Alerts:**
  - Prometheus rules (`deploy/observability/prometheus-rules.yaml`) cover deployments down,
    restarts, error rates (warning and critical), slow answers, slow search, a missing backup,
    and database connections;
  - every alert has a runbook (`docs/runbooks/alerts.md`) and a promtool unit test in CI that
    shows it fires on its condition and not otherwise;
  - the chart can install them as a `PrometheusRule`;
  - `docs/runbooks/incidents.md` covers severities, the first 15 minutes, security incidents
    and the post-incident review.

## Consequences

- The residual risks are tracked in the threat model:
  - Studio's CSP still allows inline scripts;
  - there is no per-key rate limit on answers;
  - the image is not distroless.
- An external penetration test is scheduled for Phase 5.
- Turning on image publishing needs only the repository variable; nothing else changes.
