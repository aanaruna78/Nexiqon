import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const ORG = `E2E ${Date.now().toString(36)}`;
const SLUG = ORG.toLowerCase().replace(/[^a-z0-9]+/g, "-");

async function a11y(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(
    serious.map((v) => `${label}: ${v.id} ${v.help} -> ${v.nodes.map((n) => `${n.target.join(" ")} [${n.failureSummary?.replace(/\s+/g, " ")}]`).join("; ")}`),
  ).toEqual([]);
}

/** Press Ctrl+K until the palette opens (the shortcut is live once the page has hydrated). */
async function openPalette(page: Page) {
  const input = page.getByPlaceholder("Type a command or search…").or(page.getByPlaceholder("اكتب أمرًا أو ابحث…"));
  await expect(async () => {
    await page.keyboard.press("Control+k");
    await expect(input).toBeFocused({ timeout: 1000 });
  }).toPass({ timeout: 10_000 });
}

async function signIn(page: Page) {
  await page.goto("/");
  await page.waitForURL(/realms\/nexiqon/);
  await page.fill("#username", "dev");
  await page.fill("#password", "dev-password");
  await page.click("#kc-login");
  await page.waitForURL((url) => url.host === "localhost:3100");
}

test.describe.serial("Studio", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await (await browser.newContext({ reducedMotion: "reduce" })).newPage();
    await signIn(page);
  });

  test("onboarding creates an organization and lands on Home", async () => {
    await page.goto("/onboarding");
    await a11y(page, "onboarding");
    await page.getByLabel("Organization name").fill(ORG);
    await expect(page.getByLabel("Address")).toHaveValue(SLUG);
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL("http://localhost:3100/");
    await expect(page.getByRole("heading", { name: "Welcome to Nexiqon Studio" })).toBeVisible();
    await expect(page.getByTestId("org-switcher")).toContainText(ORG);
    await expect(page.getByText(/of 5 done/)).toBeVisible();
    await a11y(page, "home");
  });

  test("skip link is the first stop for keyboard users", async () => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeFocused();
  });

  test("members: invite someone", async () => {
    await page.goto("/settings/members");
    await expect(page.getByTestId("member-dev@nexiqon.example.com")).toContainText("Owner");
    await page.getByTestId("invite-member").click();
    await page.getByLabel("Email").fill("teammate@example.com");
    await page.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByTestId("member-teammate@example.com")).toContainText("Invited");
    await a11y(page, "members");
  });

  test("API keys: secret shown once, then revoked", async () => {
    await page.goto("/settings/api-keys");
    await page.getByTestId("create-key").click();
    await page.getByLabel("Name").fill("ci-pipeline");
    await page.getByRole("button", { name: "Create API key" }).last().click();
    const secret = page.getByTestId("key-secret");
    await expect(secret).toHaveValue(/^nxq_s_[A-Za-z0-9]{12}_/);
    await a11y(page, "api key secret dialog");
    await page.getByRole("button", { name: "I have stored it" }).click();
    const row = page.getByTestId("key-ci-pipeline");
    await expect(row).toContainText("Server key");
    await row.getByRole("button", { name: /Revoke/ }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Revoke" }).click();
    await expect(row).toContainText("Revoked");
  });

  test("configuration: create, publish and deploy via the schema form", async () => {
    await page.goto("/settings/configuration/retention_profile/new");
    await page.getByLabel("Name", { exact: true }).fill("short-retention");
    await page.getByLabel("Conversations days").fill("30");
    await page.getByLabel("Traces days").fill("7");
    await a11y(page, "config editor");
    await page.getByTestId("save-draft").click();
    await page.waitForURL(/retention_profile\/short-retention$/);
    await page.getByTestId("publish").click();
    await expect(page.getByText("v1 · Published")).toBeVisible();
    await page.getByTestId("deploy").click();
    await expect(page.getByText("dev v1")).toBeVisible();
    await page.goto("/settings/configuration?kind=retention_profile");
    await expect(page.getByRole("link", { name: /short-retention/ })).toContainText("dev v1");
    await a11y(page, "configuration list");
  });

  test("configuration: client validation explains missing fields", async () => {
    await page.goto("/settings/configuration/agent/new");
    await page.getByLabel("Name", { exact: true }).fill("broken-agent");
    await page.getByTestId("save-draft").click();
    const summary = page.getByRole("alert").filter({ hasText: "Some settings need attention" });
    await expect(summary).toBeVisible();
    await expect(summary).toContainText("display_name");
  });

  test("audit: events recorded and chain verifies", async () => {
    await page.goto("/settings/audit");
    await expect(page.getByText("identity.tenant.created")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("config.deployment.changed")).toBeVisible();
    await page.getByTestId("verify-chain").click();
    await expect(page.getByTestId("chain-status")).toContainText("no tampering found");
    await a11y(page, "audit");
  });

  test("command palette navigates from the keyboard", async () => {
    await page.goto("/");
    await openPalette(page);
    await page.keyboard.type("Audit log");
    await page.keyboard.press("Enter");
    await page.waitForURL(/settings\/audit$/);
  });

  test("planned sections have designed placeholders, not dead ends", async () => {
    await page.goto("/knowledge");
    await expect(page.getByRole("heading", { name: "Knowledge is coming" })).toBeVisible();
    await a11y(page, "coming soon");
  });

  test("Arabic switches the whole UI to right-to-left", async () => {
    await page.goto("/");
    await openPalette(page);
    await page.keyboard.type("العربية");
    await page.keyboard.press("Enter");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("lang", "ar");
    await expect(page.getByRole("link", { name: "الرئيسية" }).first()).toBeVisible();
    await a11y(page, "home (ar)");
    await openPalette(page);
    await page.keyboard.type("English");
    await page.keyboard.press("Enter");
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  });

  test("sign out ends the session", async () => {
    await page.goto("/");
    await page.getByTestId("user-menu").click();
    await page.getByTestId("sign-out").click();
    await page.waitForURL(/signed-out/);
    await expect(page.getByRole("heading", { name: "You are signed out" })).toBeVisible();
    const api = await page.request.get("/api/session");
    expect(api.status()).toBe(401);
  });
});
