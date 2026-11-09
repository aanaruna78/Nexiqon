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

const GUIDE = `# Operations Guide

## Backups

Backups run every night at 02:00 UTC. Each backup is kept for 35 days and copied to a second region.

## Restores

To restore, open the console and choose Restore from backup. Large restores can take up to two hours.
`;

/** Choose an option from a labelled Radix select. */
async function pick(page: Page, label: string, option: RegExp) {
  await page.getByLabel(label).click();
  await page.getByRole("option", { name: option }).click();
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
    await expect(page.getByRole("row").filter({ hasText: "tenant.created" }).filter({ hasText: "identity" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("row").filter({ hasText: "deployment.changed" }).filter({ hasText: "config" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "tenant.created" })).toContainText("Dev User");
    await page.getByTestId("verify-chain").click();
    await expect(page.getByTestId("chain-status")).toContainText("no tampering found");
    await a11y(page, "audit");
  });

  test("knowledge: create a collection, upload files and watch them index", async () => {
    await page.goto("/knowledge");
    await expect(page.getByRole("heading", { name: "Add your first collection" })).toBeVisible();
    await a11y(page, "knowledge empty");
    await page.getByTestId("create-collection").click();
    await page.getByLabel("Name", { exact: true }).fill("Product Docs");
    await expect(page.getByLabel("Name", { exact: true })).toHaveValue("product-docs");
    await pick(page, "Model profile", /dev-offline/);
    await pick(page, "Retrieval profile", /dev-offline/);
    await a11y(page, "new collection dialog");
    await page.getByRole("button", { name: "Create collection" }).click();
    await page.waitForURL(/\/knowledge\/[0-9a-f-]{36}$/);
    await page.getByTestId("upload-input").setInputFiles([
      { name: "guide.md", mimeType: "text/markdown", buffer: Buffer.from(GUIDE) },
      { name: "archive.zip", mimeType: "application/zip", buffer: Buffer.from("PK\u0003\u0004") },
      { name: "blank.txt", mimeType: "text/plain", buffer: Buffer.from("   \n\n  ") },
    ]);
    await expect(page.getByTestId("upload-archive.zip")).toContainText("Unsupported file type"); // refused before upload
    const guide = page.getByTestId("doc-Operations Guide");
    await expect(guide).toContainText("Ready", { timeout: 60_000 });
    const blank = page.getByTestId("doc-blank.txt");
    await expect(blank).toContainText("Needs attention", { timeout: 60_000 });
    await expect(blank).toContainText("No text was found");
    await a11y(page, "collection documents");
    await guide.getByRole("button", { name: /^Operations Guide/ }).click();
    const outline = page.getByTestId("outline");
    await expect(outline).toContainText("Backups");
    await expect(outline).toContainText("Restores");
    await a11y(page, "document sheet");
    await page.keyboard.press("Escape");
  });

  test("knowledge: add a website source from the connector gallery", async () => {
    await page.getByRole("tab", { name: /Sources/ }).click();
    await page.getByTestId("add-source").click();
    await a11y(page, "connector gallery");
    await page.getByTestId("connector-web").click();
    await page.getByTestId("save-source").click();
    await expect(page.getByRole("alert").filter({ hasText: "Some settings need attention" })).toBeVisible();
    await page.getByLabel("Start urls").fill("https://docs.example.com/");
    await page.getByLabel("Start urls").press("Enter");
    await page.getByLabel("Sync right away").click();
    await a11y(page, "web connector form");
    await page.getByTestId("save-source").click();
    await expect(page.getByTestId("source-website")).toContainText("Never synced");
  });

  test("playground: grounded answer with citations and source preview", async () => {
    await page.getByRole("link", { name: "Try in Playground" }).click();
    await page.waitForURL(/\/playground\?collection=/);
    await pick(page, "Retrieval profile", /dev-offline/);
    await page.getByTestId("playground-query").fill("How long is each backup kept?");
    await page.getByTestId("playground-run").click();
    const answer = page.getByTestId("playground-answer");
    await expect(answer).toContainText("35 days");
    await expect(answer).toContainText("1 source");
    await expect(page.getByTestId("diagnostics")).toContainText("hash-ngram-1024");
    await a11y(page, "playground answer");
    await answer.getByRole("button", { name: /Source 1/ }).click();
    const preview = page.getByTestId("source-preview");
    await expect(preview).toContainText("Operations Guide");
    await expect(preview.locator("mark").first()).toBeVisible();
    await a11y(page, "source preview");
    await page.keyboard.press("Escape");
    await page.getByRole("radio", { name: "Search only" }).click();
    await page.getByTestId("playground-query").fill("zebra savannah migration");
    await page.getByTestId("playground-run").click();
    await expect(page.getByText("Weak evidence").or(page.getByText("No passages"))).toBeVisible();
  });

  test("knowledge: delete shows the impact first", async () => {
    await page.goto("/knowledge");
    await page.getByTestId("collection-product-docs").click();
    await page.getByRole("button", { name: "Delete: product-docs" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("2 documents");
    await expect(dialog).toContainText("1 connected source");
    await dialog.getByTestId("confirm-delete-collection").click();
    await page.waitForURL(/\/knowledge$/);
    await expect(page.getByRole("heading", { name: "Add your first collection" })).toBeVisible();
  });

  test("command palette navigates from the keyboard", async () => {
    await page.goto("/");
    await openPalette(page);
    await page.keyboard.type("Audit log");
    await page.keyboard.press("Enter");
    await page.waitForURL(/settings\/audit$/);
  });

  test("planned sections have designed placeholders, not dead ends", async () => {
    await page.goto("/assistants");
    await expect(page.getByRole("heading", { name: "Assistants is coming" })).toBeVisible();
    await a11y(page, "coming soon");
  });

  test("sidebar explains each section in a tooltip and shows planned ones as Soon", async () => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: /Assistants/ }).first()).toContainText("Soon");
    await expect(page.getByRole("link", { name: /Knowledge/ }).first()).not.toContainText("Soon");
    await page.getByRole("link", { name: /API keys/ }).first().hover();
    await expect(page.getByRole("tooltip")).toContainText("Keys for your backend and website widget");
  });

  test("help dialog lists keyboard shortcuts", async () => {
    await page.goto("/");
    await page.getByRole("button", { name: /Help & shortcuts/ }).click();
    const dialog = page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(dialog).toContainText("Open the command palette");
    await a11y(page, "help dialog");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
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
    await page.goto("/knowledge");
    await expect(page.getByRole("heading", { name: "المعرفة" })).toBeVisible();
    await a11y(page, "knowledge (ar)");
    await page.goto("/playground");
    await a11y(page, "playground (ar)");
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
