import { defineConfig } from "@playwright/test";

/**
 * Visual regression (UX-11): Storybook stories and the website widget, compared pixel by pixel
 * with the committed baselines. Always run inside the pinned Playwright image (same browser and
 * fonts as CI): `make visual` from the repository root, or `make visual-update` to accept changes.
 */
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.visual\.ts$/,
  snapshotPathTemplate: "{testDir}/__screenshots__/{testFileName}/{arg}{ext}",
  fullyParallel: true,
  retries: 0,
  reporter: [["list"]],
  outputDir: "../../../node_modules/.cache/studio-visual",
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.002, animations: "disabled", caret: "hide" } },
  use: {
    baseURL: "http://127.0.0.1:4400",
    viewport: { width: 1024, height: 720 },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    // Only for debugging outside the image; baselines come from the image's own Chromium.
    channel: process.env.PLAYWRIGHT_CHANNEL,
  },
  webServer: { command: "node serve.mjs", url: "http://127.0.0.1:4400/widget-harness.html", reuseExistingServer: false },
});
