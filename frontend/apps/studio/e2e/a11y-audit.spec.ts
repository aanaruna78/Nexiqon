import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, writeFileSync } from "node:fs";

import { type Browser, expect, type Page, test } from "@playwright/test";

/**
 * UX-10 accessibility audit: every Studio page, in every UI language and both themes, scanned
 * with axe (WCAG 2.2 AA). Serious and critical findings fail; every finding, of any impact, is
 * written to the audit file (docs/qa/2026-11-20-accessibility-audit.md summarises it).
 */
const PAGES = [
  "/",
  "/admin",
  "/admin/get-started",
  "/admin/assistants",
  "/admin/knowledge",
  "/admin/playground",
  "/admin/conversations",
  "/admin/insights",
  "/admin/evaluations",
  "/admin/domain-packs",
  "/admin/actions",
  "/settings",
  "/admin/members",
  "/admin/api-keys",
  "/admin/audit",
  "/admin/configuration",
  "/admin/models",
  "/admin/organization",
  "/admin/webhooks",
];
// The first detail page linked from each list, when there is one.
const DETAILS: [string, RegExp][] = [
  ["/admin/assistants", /^\/admin\/assistants\/[^/]+$/],
  ["/admin/knowledge", /^\/admin\/knowledge\/[^/]+$/],
  ["/admin/evaluations", /^\/admin\/evaluations\/[^/]+$/],
  ["/admin/domain-packs", /^\/admin\/domain-packs\/[^/]+$/],
];
const RUNS: { locale: string; scheme: "light" | "dark" }[] = [
  { locale: "en", scheme: "light" },
  { locale: "en", scheme: "dark" },
  { locale: "fr", scheme: "light" },
  { locale: "es", scheme: "light" },
  { locale: "ar", scheme: "light" },
  { locale: "ar", scheme: "dark" },
];

type Finding = { run: string; page: string; id: string; impact: string; help: string; nodes: string[] };
const findings: Finding[] = [];
const scanned: string[] = [];

async function signedIn(browser: Browser, locale: string, scheme: "light" | "dark"): Promise<Page> {
  const context = await browser.newContext({ reducedMotion: "reduce", colorScheme: scheme });
  await context.addCookies([{ name: "NEXT_LOCALE", value: locale, url: "http://localhost:3100" }]);
  const page = await context.newPage();
  await page.goto("/");
  await page.waitForURL(/realms\/nexiqon/);
  await page.fill("#username", "dev");
  await page.fill("#password", "dev-password");
  await page.click("#kc-login");
  await page.waitForURL((url) => url.host === "localhost:3100");
  if (page.url().includes("/select-org")) {
    // The most recent end-to-end organization has content on every page; else the first one.
    const e2e = page.getByRole("button", { name: /^E2E / });
    await (await e2e.count() ? e2e.last() : page.getByRole("button").first()).click();
    await page.waitForURL((url) => !url.pathname.startsWith("/select-org"));
  }
  if (page.url().includes("/onboarding")) {
    await page.locator("input").first().fill(`Audit ${Date.now().toString(36)}`);
    await page.locator("button[type=submit]").click();
    await page.waitForURL("http://localhost:3100/");
  }
  return page;
}

async function scan(page: Page, run: string, path: string) {
  await expect(page).toHaveTitle(/\S/);
  await page.waitForLoadState("networkidle");
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  scanned.push(`${run} ${path}`);
  for (const v of results.violations) {
    findings.push({
      run,
      page: path,
      id: v.id,
      impact: v.impact ?? "unknown",
      help: v.help,
      nodes: v.nodes.map((n) => n.target.join(" ")),
    });
  }
}

test.describe.serial("accessibility audit (UX-10)", () => {
  for (const { locale, scheme } of RUNS) {
    test(`${locale}, ${scheme} theme`, async ({ browser }) => {
      test.setTimeout(8 * 60_000);
      const run = `${locale}/${scheme}`;
      const page = await signedIn(browser, locale, scheme);
      await expect(page.locator("html")).toHaveAttribute("lang", locale);
      for (const path of PAGES) {
        await page.goto(path);
        await scan(page, run, path);
      }
      for (const [list, detail] of DETAILS) {
        await page.goto(list);
        await page.waitForLoadState("networkidle");
        const hrefs = await page.locator("main a[href]").evaluateAll((as) => as.map((a) => (a as HTMLAnchorElement).href));
        const href = hrefs.map((h) => new URL(h).pathname).find((h) => detail.test(h));
        if (href) {
          await page.goto(href);
          await scan(page, run, href.replace(/\/[^/]+$/, "/[id]"));
        }
      }
      await page.context().close();
      const blocking = findings.filter((f) => f.run === run && ["serious", "critical"].includes(f.impact));
      expect(blocking.map((f) => `${f.page}: ${f.id} (${f.impact}) ${f.nodes.join(", ")}`)).toEqual([]);
    });
  }

  test.afterAll(() => {
    mkdirSync("../../node_modules/.cache/studio-e2e", { recursive: true });
    writeFileSync(
      "../../node_modules/.cache/studio-e2e/a11y-audit.json",
      JSON.stringify({ scanned: scanned.length, pages: scanned, findings }, null, 2),
    );
  });
});
