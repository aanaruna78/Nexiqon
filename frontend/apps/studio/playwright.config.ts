import { defineConfig } from "@playwright/test";

/**
 * End-to-end tests against the full local stack:
 *   make dev-up PROFILES=platform,apps   (gateway :8000, Keycloak :8080)
 *   Studio on :3100                      (pnpm build && pnpm start, see e2e/README.md)
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.STUDIO_BASE_URL ?? "http://localhost:3100",
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome",
    trace: "retain-on-failure",
    locale: "en-GB",
    // axe measures settled colours (not mid-animation); also exercises our reduced-motion styles.
    reducedMotion: "reduce",
  },
});
