import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

/** Every story of the design-system catalog, light and dark, left-to-right and right-to-left. */
const index = JSON.parse(readFileSync(join(__dirname, "../storybook-static/index.json"), "utf8")) as {
  entries: Record<string, { id: string; type: string }>;
};
const stories = Object.values(index.entries).filter((e) => e.type === "story").map((e) => e.id);

for (const id of stories) {
  for (const theme of ["light", "dark"]) {
    for (const direction of ["ltr", "rtl"]) {
      test(`${id} ${theme} ${direction}`, async ({ page }) => {
        await page.goto(`/sb/iframe.html?id=${id}&viewMode=story&globals=theme:${theme};direction:${direction}`);
        await expect(page.locator("#storybook-root > *").first()).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        await expect(page).toHaveScreenshot(`${id}-${theme}-${direction}.png`, { fullPage: true });
      });
    }
  }
}
