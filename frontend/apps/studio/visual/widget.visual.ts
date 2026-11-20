import { expect, type Page, test } from "@playwright/test";

/** The website widget's main states, light, dark and Arabic, against a mocked gateway. */
const SETTINGS = {
  agent: "support",
  locale: "en",
  title: "Help",
  assistant_name: "Acme Help",
  greeting: "Hi! Ask me anything about Acme.",
  starter_questions: ["How do I invite a teammate?", "Where are my invoices?"],
  accent_color: "#0E8A7E",
  handoff: true,
};
const turn = (content: string, extra: Record<string, unknown> = {}, status = "active") => ({
  conversation: { id: "c1", status },
  user_message: null,
  reply: { id: "m1", role: "assistant", content, contract: { kind: "grounded", ...extra } },
});
const ANSWER = turn("Open Settings, then Members, and choose Invite [1]. Invitations expire after 7 days [2].", {
  citations: [
    { marker: "1", citation: "Admin Guide › Teammates", source_uri: "https://docs.example.com/admin#teammates" },
    { marker: "2", citation: "Admin Guide › Invitations", source_uri: "https://docs.example.com/admin#invitations" },
  ],
});
const APPROVAL = turn("Open a support case titled “Login fails”?", { kind: "approval", interrupt: { kind: "approval", prompt: "Open a support case titled “Login fails”?" } }, "awaiting_approval");

async function mount(page: Page, attrs: Record<string, string>, reply = ANSWER) {
  await page.route("https://gw.example.test/**", async (route) => {
    const url = route.request().url();
    const json = (body: unknown) => route.fulfill({ json: body });
    if (url.includes("/channel/v1/channels/widget/")) return json({ ...SETTINGS, locale: attrs.locale ?? "en" });
    if (url.endsWith("/messages/stream")) {
      const body = `event: message\ndata: ${JSON.stringify(reply)}\n\n`;
      return route.fulfill({ body, headers: { "content-type": "text/event-stream" } });
    }
    if (url.endsWith("/conversation/v1/conversations")) return json({ id: "c1", status: "active" });
    return json({});
  });
  await page.goto("/widget-harness.html");
  if (attrs.theme === "dark") await page.evaluate(() => document.body.classList.add("dark"));
  await page.evaluate((a) => {
    const el = document.createElement("nexiqon-chat");
    for (const [k, v] of Object.entries({ agent: "support", "api-base": "https://gw.example.test", "api-key": "nxq_visual", ...a })) el.setAttribute(k, v);
    document.body.append(el);
  }, attrs);
  await page.evaluate(() => customElements.whenDefined("nexiqon-chat"));
}

const launcher = (page: Page) => page.locator("nexiqon-chat").locator("button").first();

for (const [name, attrs] of [
  ["light", { theme: "light" }],
  ["dark", { theme: "dark" }],
  ["arabic", { theme: "light", locale: "ar" }],
] as [string, Record<string, string>][]) {
  test(`launcher ${name}`, async ({ page }) => {
    await mount(page, attrs);
    await expect(launcher(page)).toBeVisible();
    await expect(page).toHaveScreenshot(`launcher-${name}.png`);
  });

  test(`greeting ${name}`, async ({ page }) => {
    await mount(page, attrs);
    await launcher(page).click();
    await expect(page.locator("nexiqon-chat").getByRole("textbox")).toBeVisible();
    await expect(page).toHaveScreenshot(`greeting-${name}.png`);
  });

  test(`answer with sources ${name}`, async ({ page }) => {
    await mount(page, attrs);
    await launcher(page).click();
    const box = page.locator("nexiqon-chat").getByRole("textbox");
    await box.fill("How do I invite a teammate?");
    await box.press("Enter");
    await expect(page.locator("nexiqon-chat").getByRole("link").first()).toBeVisible();
    await expect(page).toHaveScreenshot(`answer-${name}.png`);
  });
}

test("confirmation before an action", async ({ page }) => {
  await mount(page, { theme: "light" }, APPROVAL);
  await launcher(page).click();
  const box = page.locator("nexiqon-chat").getByRole("textbox");
  await box.fill("My login fails, please open a case");
  await box.press("Enter");
  await expect(page.locator("nexiqon-chat").getByRole("button", { name: /yes|approve|go ahead/i }).first()).toBeVisible();
  await expect(page).toHaveScreenshot("approval-light.png");
});
