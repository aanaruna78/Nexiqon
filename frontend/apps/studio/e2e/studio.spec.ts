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

const PACK = "ops-desk";
const OPENAPI = `openapi: 3.0.3
info: { title: Status API, version: "1.0" }
servers: [{ url: "https://status.example.com" }]
paths:
  /orders/{order_id}/status:
    get:
      operationId: getOrderStatus
      summary: Look up an order's status
      parameters:
        - { name: order_id, in: path, required: true, schema: { type: string } }
      responses: { "200": { description: ok } }
`;

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

  test("domain packs: create from the template, edit and release", async () => {
    await page.goto("/domain-packs");
    await a11y(page, "packs");
    await page.getByTestId("new-pack").click();
    await page.getByLabel("Title").fill("Ops desk");
    await page.getByTestId("create-pack").click();
    await page.waitForURL(new RegExp(`/domain-packs/${PACK}$`));
    await a11y(page, "pack overview");
    await page.getByTestId("pack-tab-intents").click();
    await page.getByLabel("Examples").first().fill("How long are backups kept?");
    await page.getByLabel("Examples").first().press("Enter");
    await a11y(page, "pack intents");
    // The offline development models score lower than real ones (ADR 0020).
    await page.getByTestId("pack-tab-safety").click();
    await page.getByLabel("Minimum evidence (0–1)").fill("0.15");
    await page.getByTestId("pack-tab-widget").click();
    await page.getByLabel("Greeting").fill("Hi! Ask me about operations.");
    await a11y(page, "pack widget");
    await page.getByTestId("save-pack").click();
    await expect(page.getByText("Draft v1 saved")).toBeVisible(); // a new pack is still draft v1
    await page.getByTestId("pack-tab-workflow").click();
    await page.getByTestId("validate-graph").click();
    await expect(page.getByText("The workflow is valid.")).toBeVisible();
    await a11y(page, "pack workflow");
    await page.getByTestId("pack-tab-versions").click();
    await expect(page.getByText("Nothing to compare yet")).toBeVisible();
    await page.getByTestId("release").click();
    await expect(page.getByTestId("live-version")).toHaveText("Version 1");
    await a11y(page, "pack versions");
    await page.getByTestId("pack-tab-yaml").click();
    await page.getByTestId("export-pack").click();
    await expect(page.getByTestId("pack-yaml")).toContainText("Hi! Ask me about operations.");
  });

  test("assistants: create, test with streaming and inspect an answer", async () => {
    await page.goto("/assistants");
    await page.getByTestId("new-assistant").click();
    await page.getByLabel("Name people see").fill("Ops Helper");
    await page.getByLabel("product-docs").check();
    await pick(page, "Model profile", /dev-offline/);
    await pick(page, "Retrieval profile", /dev-offline/);
    await a11y(page, "new assistant");
    await page.getByTestId("create-assistant").click();
    await page.waitForURL(/\/assistants\/ops-helper\?tab=test/);
    await page.getByTestId("test-input").fill("How long is each backup kept?");
    await page.getByTestId("test-send").click();
    const log = page.getByTestId("test-chat-log");
    await expect(log).toContainText("35 days");
    await expect(log).toContainText("Grounded");
    await a11y(page, "test chat");
    await log.getByTestId("inspect").last().click();
    const inspector = page.getByTestId("inspector");
    await expect(inspector.getByTestId("why")).toContainText("verified citation");
    await expect(inspector.getByTestId("inspector-sources")).toContainText("Backups");
    await expect(inspector.getByTestId("inspector-facts")).toContainText("Completed");
    await a11y(page, "answer inspector");
    await page.keyboard.press("Escape");
  });

  test("assistants: access preview shows what a website visitor can retrieve", async () => {
    await page.getByTestId("tab-access").click();
    await page.getByLabel("A website visitor (widget)").check();
    await page.getByTestId("view-as-query").fill("backups");
    await page.getByTestId("view-as-run").click();
    await expect(page.getByTestId("view-as-summary")).toContainText(/visible/);
    await a11y(page, "access preview");
  });

  test("assistants: change, review the diff, release and roll back", async () => {
    await page.getByTestId("tab-setup").click();
    await page.getByRole("combobox", { name: "Tone", exact: true }).click();
    await page.getByRole("option", { name: "Formal" }).click();
    await page.getByTestId("save-assistant").click();
    await page.waitForURL(/tab=versions/);
    await expect(page.getByTestId("diff")).toContainText("Added");
    await expect(page.getByTestId("diff")).toContainText('"tone":"formal"');
    await a11y(page, "assistant versions");
    await page.getByTestId("release").click();
    await expect(page.getByTestId("live-version")).toHaveText("Version 2");
    await page.getByTestId("rollback").click();
    await expect(page.getByTestId("live-version")).toHaveText("Version 1");
    await page.getByTestId("tab-workflow").click();
    await expect(page.getByRole("img", { name: /Workflow with 6 steps/ })).toBeVisible();
  });

  test("actions: import an API from OpenAPI and dry-run it", async () => {
    await page.goto("/actions?tab=connect");
    await page.getByTestId("openapi-spec").fill(OPENAPI);
    await page.getByTestId("openapi-read").click();
    await expect(page.getByText("Reads data")).toBeVisible();
    await a11y(page, "openapi import");
    await page.getByTestId("openapi-add").click();
    await expect(page.getByText(/1 tool added/)).toBeVisible();
    await page.getByTestId("actions-tab-tools").click();
    const list = page.getByTestId("tool-list");
    await expect(list).toContainText("get-order-status");
    await a11y(page, "tools");
    await page.getByTestId("try-get-order-status").click();
    await page.getByLabel("Arguments (JSON)").fill('{"order_id": "A-17"}');
    await page.getByTestId("dry-run-go").click();
    await expect(page.getByTestId("dry-run-request")).toContainText("https://status.example.com/orders/A-17/status");
    await a11y(page, "dry run");
    await page.keyboard.press("Escape");
    await page.getByTestId("actions-tab-approvals").click();
    await page.getByTestId("actions-tab-calls").click();
    await a11y(page, "call log");
  });

  test("models: plain-language trade-offs and where data goes", async () => {
    await page.goto("/settings/models");
    await expect(page.getByTestId("data-flow")).toContainText("Restricted");
    await expect(page.getByTestId("profiles")).toContainText("dev-offline");
    await a11y(page, "models");
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
    await page.goto("/conversations");
    await expect(page.getByRole("heading", { name: "Conversations is coming" })).toBeVisible();
    await a11y(page, "coming soon");
  });

  test("sidebar explains each section in a tooltip and shows planned ones as Soon", async () => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: /Conversations/ }).first()).toContainText("Soon");
    await expect(page.getByRole("link", { name: /Assistants/ }).first()).not.toContainText("Soon");
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
    await page.goto("/assistants");
    await expect(page.getByRole("heading", { name: "المساعدون" })).toBeVisible();
    await a11y(page, "assistants (ar)");
    await page.goto(`/domain-packs/${PACK}?tab=widget`);
    await a11y(page, "pack widget (ar)");
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
