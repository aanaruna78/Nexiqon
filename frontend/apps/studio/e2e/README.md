# Studio end-to-end tests

```bash
make dev-up PROFILES=platform,apps                     # from the repo root
cd frontend/apps/studio
pnpm build
STUDIO_SESSION_SECRET=$(openssl rand -hex 32) STUDIO_ALLOW_INSECURE_IDP=1 pnpm start -p 3100 &
pnpm e2e
```

Signs in through the dev Keycloak realm (`dev` / `dev-password`), creates a fresh organization and
exercises members, API keys, configuration, audit, the command palette, Arabic (RTL) and sign-out.
Every screen is scanned with axe (WCAG 2.2 AA); serious or critical violations fail the test.
