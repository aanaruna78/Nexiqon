# ADR 0016: Studio as a backend-for-frontend, OIDC sessions and i18n

Status: Accepted (2026-11-08)

## Decision

- **Backend-for-frontend.** The browser talks only to Studio's Next.js server. Route handler
  `/api/nx/*` attaches the access token and the selected tenant (`X-Nexiqon-Tenant`) and forwards to the
  gateway. Tokens never reach browser JavaScript.
- **Sessions.** Authorization code + PKCE (openid-client) against any OIDC provider (Keycloak in dev,
  Auth0, Clerk-as-OIDC later). The session is an encrypted (JWE dir/A256GCM) httpOnly SameSite=Lax cookie
  with transparent refresh; the ID token is kept in a separate encrypted cookie only as the logout hint.
- **CSRF.** Mutations through the BFF need `X-Nexiqon-CSRF: 1` and a same-origin `Origin` header.
- **Upstream safety.** The BFF builds upstream URLs that cannot leave the gateway origin.
- **i18n.** next-intl without locale routing (cookie / Accept-Language); English, Arabic (RTL via `dir`
  and Radix `DirectionProvider`), and a generated pseudo-locale `en-XA` to catch hard-coded strings and
  truncation. Domain Pack vocabulary overrides UI terms (`/config/v1/vocabulary`).
- **UI system.** shadcn/ui on Radix with Nexiqon tokens (WCAG AA pairs), Storybook catalog with the
  a11y addon, schema-driven forms from the config JSON Schemas.

## Why

Keeps credentials out of the browser (XSS cannot steal tokens), works with every IdP we support, and
makes accessibility, RTL and domain vocabulary properties of the platform rather than per-screen work.

## Consequences

- A native Clerk adapter (Clerk components and session tokens) is a follow-up; `STUDIO_AUTH_PROVIDER=clerk`
  currently answers 501 with guidance.
- Every Studio page is per-user; Next.js Cache Components stay off until there is cacheable content.
