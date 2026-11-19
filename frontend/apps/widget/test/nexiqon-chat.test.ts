import "../src/nexiqon-chat";
import { ChatClient, parseSSE, visitorId } from "../src/client";
import { isUnsure, nextSuggestions, readableTheme, type NexiqonChat } from "../src/nexiqon-chat";

const SETTINGS = {
  agent: "support",
  locale: "en",
  title: "Help",
  assistant_name: "Acme Help",
  greeting: "Hi! Ask me anything.",
  starter_questions: ["How do I get started?"],
  accent_color: "#0E8A7E",
  handoff: true,
};

function sse(events: [string, unknown][]): ReadableStream<Uint8Array> {
  const text = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  const bytes = new TextEncoder().encode(text);
  // Deliberately split mid-event to exercise buffering.
  const cut = Math.floor(bytes.length / 2);
  return new ReadableStream({
    start(c) {
      c.enqueue(bytes.slice(0, cut));
      c.enqueue(bytes.slice(cut));
      c.close();
    },
  });
}

const turn = (content: string, extra: Record<string, unknown> = {}, status = "active") => ({
  conversation: { id: "c1", status },
  user_message: null,
  reply: { id: "m1", role: "assistant", content, contract: { kind: "grounded", ...extra } },
});

interface Call {
  method: string;
  url: string;
  headers: Record<string, string>;
  body?: unknown;
}

function fakeFetch(routes: Record<string, () => Response>, calls: Call[]): typeof fetch {
  return (async (url: string, init: RequestInit) => {
    calls.push({
      method: init.method ?? "GET",
      url,
      headers: init.headers as Record<string, string>,
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    });
    const key = Object.keys(routes).find((k) => url.includes(k));
    return key ? routes[key]() : new Response("{}", { status: 404 });
  }) as unknown as typeof fetch;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function mount(attrs = 'agent="support" api-base="https://gw.test" api-key="nxq_x"') {
  localStorage.clear();
  document.body.innerHTML = `<nexiqon-chat ${attrs}></nexiqon-chat>`;
  const el = document.querySelector("nexiqon-chat") as NexiqonChat;
  await el.updateComplete;
  return el;
}

function wire(el: NexiqonChat, routes: Record<string, () => Response>): Call[] {
  const calls: Call[] = [];
  el.client = new ChatClient("https://gw.test", "nxq_x", "support", "v".repeat(32), fakeFetch(routes, calls));
  return calls;
}

const root = (el: NexiqonChat) => el.shadowRoot!;
const flush = async (el: NexiqonChat) => {
  for (let i = 0; i < 5; i++) {
    await new Promise((r) => setTimeout(r, 0));
    await el.updateComplete;
  }
};

describe("client", () => {
  it("parses server-sent events split across chunks", async () => {
    const got = [];
    for await (const e of parseSSE(sse([["delta", { text: "Hel" }], ["delta", { text: "lo" }]]))) got.push(e);
    expect(got).toEqual([
      { event: "delta", data: { text: "Hel" } },
      { event: "delta", data: { text: "lo" } },
    ]);
  });

  it("keeps one random visitor id per browser", () => {
    localStorage.clear();
    const id = visitorId();
    expect(id).toMatch(/^[A-Za-z0-9_-]{22,64}$/);
    expect(visitorId()).toBe(id);
  });

  it("sends the widget key and the visitor id, never anything else", async () => {
    const calls: Call[] = [];
    const c = new ChatClient("https://gw.test/", "nxq_x", "support", "v".repeat(32), fakeFetch({ "/widget/": () => json(SETTINGS) }, calls));
    await c.settings("en");
    expect(calls[0].url).toBe("https://gw.test/channel/v1/channels/widget/agents/support?locale=en");
    expect(calls[0].headers).toEqual({ authorization: "Bearer nxq_x", "x-nexiqon-visitor": "v".repeat(32) });
  });
});

describe("<nexiqon-chat>", () => {
  it("registers and starts closed", async () => {
    expect(customElements.get("nexiqon-chat")).toBeDefined();
    const el = await mount('agent="support"');
    expect(root(el).querySelector(".launcher")!.getAttribute("aria-expanded")).toBe("false");
    expect(root(el).querySelector("section")).toBeNull();
  });

  it("opens with the pack's title, greeting, starters and theme colour", async () => {
    const el = await mount();
    wire(el, { "/widget/": () => json(SETTINGS) });
    const seen: boolean[] = [];
    el.addEventListener("nexiqon-toggle", (e) => seen.push((e as CustomEvent).detail.open));
    await el.toggle();
    await flush(el);
    expect(root(el).querySelector("h2")!.textContent).toBe("Help");
    expect(root(el).textContent).toContain("Hi! Ask me anything.");
    expect(root(el).querySelector(".chips button")!.textContent).toBe("How do I get started?");
    expect(el.style.getPropertyValue("--nx-on-accent")).toBe("#ffffff");
    expect(el.style.getPropertyValue("--nx-accent")).not.toBe("");
    expect(seen).toEqual([true]);
  });

  it("streams an answer, then shows the checked text with its citations", async () => {
    const el = await mount();
    const stream = [
      ["status", { stage: "searching" }],
      ["delta", { text: "Open Settings " }],
      ["delta", { text: "[1]." }],
      ["message", turn("Open Settings [1].", { citations: [{ marker: "1", citation: "Admin Guide › Teammates", source_uri: "https://docs.test/a" }] })],
    ] as [string, unknown][];
    const calls = wire(el, {
      "/widget/": () => json(SETTINGS),
      "/messages/stream": () => new Response(sse(stream), { headers: { "content-type": "text/event-stream" } }),
      "/conversations": () => json({ id: "c1", status: "active" }, 201),
    });
    await el.toggle();
    await flush(el);
    await el.send("How do I invite a teammate?");
    await flush(el);
    const msgs = [...root(el).querySelectorAll(".msg.assistant")].map((m) => m.textContent!.trim());
    expect(msgs.at(-1)).toContain("Open Settings [1].");
    const link = root(el).querySelector(".sources a") as HTMLAnchorElement;
    expect(link.href).toBe("https://docs.test/a");
    expect(link.rel).toContain("noopener");
    expect(calls.find((c) => c.url.endsWith("/messages/stream"))!.body).toEqual({ content: "How do I invite a teammate?" });
    expect(localStorage.getItem("nexiqon:conversation:support")).toBe("c1");
  });

  it("renders answers as text, never as HTML", async () => {
    const el = await mount();
    wire(el, {
      "/widget/": () => json(SETTINGS),
      "/messages/stream": () => new Response(sse([["message", turn('<img src=x onerror="alert(1)">')]])),
      "/conversations": () => json({ id: "c1", status: "active" }, 201),
    });
    await el.toggle();
    await el.send("hi");
    await flush(el);
    expect(root(el).querySelector(".log img")).toBeNull();
    expect(root(el).textContent).toContain("<img");
  });

  it("asks for approval with buttons and sends the decision", async () => {
    const el = await mount();
    const approval = turn("Should I go ahead?", { kind: "approval", interrupt: { kind: "approval" } }, "awaiting_approval");
    const calls = wire(el, {
      "/widget/": () => json(SETTINGS),
      "/messages/stream": () => new Response(sse([["message", approval]])),
      "/approval": () => json(turn("Done.")),
      "/conversations": () => json({ id: "c1", status: "active" }, 201),
    });
    await el.toggle();
    await el.send("please open a request");
    await flush(el);
    const yes = root(el).querySelector(".actions button.primary") as HTMLButtonElement;
    expect(yes.textContent!.trim()).toBe("Yes, go ahead");
    expect((root(el).querySelector("form button") as HTMLButtonElement).disabled).toBe(true);
    yes.click();
    await flush(el);
    expect(calls.find((c) => c.url.endsWith("/approval"))!.body).toEqual({ approved: true });
    expect(root(el).querySelector(".actions")).toBeNull();
  });

  it("hands over to a person and says so", async () => {
    const el = await mount();
    const calls = wire(el, {
      "/widget/": () => json(SETTINGS),
      "/handoff": () => json(turn("I'm passing this to a person.", { kind: "handoff" }, "escalated")),
      "/conversations": () => json({ id: "c1", status: "active" }, 201),
    });
    await el.toggle();
    await flush(el);
    const button = [...root(el).querySelectorAll("header button")].find((b) => b.textContent!.includes("Talk to a person")) as HTMLButtonElement;
    button.click();
    await flush(el);
    expect(calls.some((c) => c.url.endsWith("/conversations/c1/handoff") && c.method === "POST")).toBe(true);
    expect(root(el).textContent).toContain("A person from the team will pick this up here.");
    expect(button.disabled).toBe(true);
  });

  it("offers a retry when a turn fails", async () => {
    const el = await mount();
    wire(el, {
      "/widget/": () => json(SETTINGS),
      "/messages/stream": () => json({ detail: "boom" }, 502),
      "/conversations": () => json({ id: "c1", status: "active" }, 201),
    });
    await el.toggle();
    await el.send("hello");
    await flush(el);
    expect(root(el).querySelector('[role="alert"]')!.textContent).toContain("Try again");
  });

  it("keeps text on the theme colour readable (WCAG AA)", () => {
    expect(readableTheme("#0b6f66")).toEqual({ accent: "#0b6f66", ink: "#ffffff" });
    expect(readableTheme("#FFD54F")).toEqual({ accent: "#FFD54F", ink: "#12233f" });
    const adjusted = readableTheme("#0E8A7E")!; // 4.2:1 with white, 3.7:1 with ink: darkened
    expect(adjusted.ink).toBe("#ffffff");
    expect(adjusted.accent).not.toBe("#0E8A7E");
    expect(readableTheme("nope")).toBeNull();
  });
});

describe("W-01..W-04", () => {
  const RICH = {
    ...SETTINGS,
    suggestions: ["How do I get started?", "What plan am I on?", "How do I reset my password?", "How do I invite a teammate?"],
    labels: { person: "Contact support", sources: "Product documentation" },
    theme: "dark",
    feedback: true,
    transcript_email: true,
  };
  const chat = (el: NexiqonChat, reply = turn("Open Settings [1].", { citations: [{ marker: "1", citation: "Guide" }] })) =>
    wire(el, {
      "/widget/": () => json(RICH),
      "/messages/stream": () => new Response(sse([["message", reply]])),
      "/feedback": () => new Response(null, { status: 204 }),
      "/transcript": () => json({ sent: true, next_allowed_at: "2026-11-19T10:10:00Z" }, 202),
      "/handoff": () => json(turn("I'm passing this to a person.", { kind: "handoff" }, "escalated")),
      "/conversations": () => json({ id: "c1", status: "active" }, 201),
    });

  it("uses the pack's words and theme, and the page can force light", async () => {
    const el = await mount();
    chat(el);
    await el.toggle();
    await flush(el);
    expect(root(el).querySelector("header button")!.textContent!.trim()).toBe("Contact support");
    expect(el.dataset.theme).toBe("dark");
    el.theme = "light";
    await flush(el);
    expect(el.dataset.theme).toBe("light");
  });

  it("an inline widget is always open, with no launcher", async () => {
    const el = await mount('agent="support" mode="inline"'); // no gateway: nothing leaves the test
    await flush(el);
    expect(root(el).querySelector("section")!.getAttribute("role")).toBe("region");
    expect(root(el).querySelector(".launcher")).toBeNull();
  });

  it("speaks French and German, and lays out Arabic right to left", async () => {
    for (const [locale, open, dir] of [["fr", "Poser une question", "ltr"], ["de-DE", "Frage stellen", "ltr"], ["ar", "اطرح سؤالًا", "rtl"]]) {
      const el = await mount(`agent="support" locale="${locale}"`);
      expect(root(el).querySelector(".launcher")!.textContent!.trim()).toBe(open);
      el.open = true;
      await flush(el);
      expect(root(el).querySelector("section")!.getAttribute("dir")).toBe(dir);
    }
  });

  it("Escape closes the chat and puts focus back on the launcher", async () => {
    const el = await mount();
    chat(el);
    await el.toggle();
    await flush(el);
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, composed: true }));
    await flush(el);
    expect(el.open).toBe(false);
    expect(el.shadowRoot!.activeElement).toBe(root(el).querySelector(".launcher"));
  });

  it("announces each finished answer once, not every streamed word", async () => {
    const el = await mount();
    chat(el);
    await el.toggle();
    await el.send("How do I invite a teammate?");
    await flush(el);
    expect(root(el).querySelector('.sr[aria-live="polite"]')!.textContent).toBe("Acme Help answered: Open Settings [1].");
  });

  it("is honest when unsure and offers a person in one tap", async () => {
    const el = await mount();
    const calls = chat(el, turn("I couldn't find that in the documentation.", { abstained: true }));
    await el.toggle();
    await el.send("What is the CEO's address?");
    await flush(el);
    const bubble = root(el).querySelector(".msg.assistant.unsure")!;
    expect(bubble.textContent).toContain("Not sure");
    expect(root(el).querySelector(".rate")).toBeNull(); // nothing to rate
    const ask = [...root(el).querySelectorAll(".turn button")].find((b) => b.textContent!.includes("Ask a person instead")) as HTMLButtonElement;
    ask.click();
    await flush(el);
    expect(calls.some((c) => c.url.endsWith("/conversations/c1/handoff"))).toBe(true);
  });

  it("confirmation cards need a tap; typed text cannot approve", async () => {
    const el = await mount();
    chat(el, turn("Open a support case titled 'Login fails'?", { kind: "approval", interrupt: { kind: "approval", prompt: "Open a support case titled 'Login fails'?" } }, "awaiting_approval"));
    await el.toggle();
    await el.send("open a case please");
    await flush(el);
    const card = root(el).querySelector(".card")!;
    expect(card.getAttribute("role")).toBe("group");
    expect(card.textContent).toContain("Please confirm");
    expect((root(el).querySelector("textarea.input") as HTMLTextAreaElement).disabled).toBe(true);
    await el.send("yes");
    expect(root(el).querySelector(".card")).not.toBeNull();
  });

  it("rates answers, asking what was missing when one did not help", async () => {
    const el = await mount();
    const calls = chat(el);
    await el.toggle();
    await el.send("How do I invite a teammate?");
    await flush(el);
    const [up, down] = [...root(el).querySelectorAll(".rate button")] as HTMLButtonElement[];
    up.click();
    await flush(el);
    expect(calls.find((c) => c.url.endsWith("/messages/m1/feedback"))!.body).toEqual({ rating: "up" });
    expect(up.getAttribute("aria-pressed")).toBe("true");
    down.click();
    await flush(el);
    const why = root(el).querySelector("form.why") as HTMLFormElement;
    (why.querySelector("textarea") as HTMLTextAreaElement).value = "It skipped the admin step";
    why.requestSubmit();
    await flush(el);
    expect(calls.filter((c) => c.url.endsWith("/feedback")).at(-1)!.body).toEqual({ rating: "down", comment: "It skipped the admin step" });
  });

  it("suggests follow-ups the visitor has not asked yet", async () => {
    const el = await mount();
    chat(el);
    await el.toggle();
    await el.send("how do I get STARTED?");
    await flush(el);
    const offered = [...root(el).querySelectorAll(".suggest button")].map((b) => b.textContent!.trim());
    expect(offered).toEqual(["What plan am I on?", "How do I reset my password?", "How do I invite a teammate?"]);
    expect(nextSuggestions(["a", "b"], ["A "])).toEqual(["b"]);
  });

  it("emails a copy of the conversation and explains when it cannot", async () => {
    const el = await mount();
    const calls = chat(el);
    await el.toggle();
    expect(root(el).querySelector("footer")).toBeNull(); // nothing to send yet
    await el.send("How do I invite a teammate?");
    await flush(el);
    (root(el).querySelector("footer .linkish") as HTMLButtonElement).click();
    await flush(el);
    await el.emailCopy(" me@example.com ");
    await flush(el);
    expect(calls.find((c) => c.url.endsWith("/conversations/c1/transcript"))!.body).toEqual({ email: "me@example.com" });
    expect(root(el).querySelector('footer [role="status"]')!.textContent).toBe("Sent. Check your inbox.");
    el.client = new ChatClient("https://gw.test", "nxq_x", "support", "v".repeat(32), fakeFetch({ "/transcript": () => json({ code: "transcript_too_soon" }, 429) }, []));
    await el.emailCopy("me@example.com");
    await flush(el);
    expect(root(el).querySelector('footer [role="status"]')!.textContent).toContain("in a few minutes");
  });

  it("knows which answers it could not stand behind", () => {
    expect(isUnsure({ role: "assistant", contract: { abstained: true, kind: "grounded" } })).toBe(true);
    expect(isUnsure({ role: "assistant", contract: { abstained: true, kind: "handoff" } })).toBe(false);
    expect(isUnsure({ role: "assistant", contract: { abstained: false } })).toBe(false);
  });
});

describe("talking with the team (ST-16)", () => {
  it("shows a team member's reply while the conversation is with a person", async () => {
    const el = await mount();
    let history = [
      { id: "u1", role: "user", content: "I want a person", contract: {} },
      { id: "m1", role: "assistant", content: "I'm passing this to a person.", contract: { kind: "handoff" } },
    ];
    wire(el, {
      "/widget/": () => json(SETTINGS),
      "/handoff": () => json(turn("I'm passing this to a person.", { kind: "handoff" }, "escalated")),
      "/conversations/c1": () => json({ id: "c1", status: "escalated", messages: history }),
      "/conversations": () => json({ id: "c1", status: "active" }, 201),
    });
    await el.toggle();
    await el.askForPerson();
    await flush(el);
    history = [...history, { id: "s1", role: "staff", content: "Hi, Sam here. Let me check.", contract: { kind: "human" } }];
    await el.refresh();
    await flush(el);
    const staff = root(el).querySelector(".msg.staff")!;
    expect(staff.textContent).toContain("Team");
    expect(staff.textContent).toContain("Hi, Sam here. Let me check.");
    await el.refresh(); // nothing new: no duplicate
    await flush(el);
    expect(root(el).querySelectorAll(".msg.staff").length).toBe(1);
    el.open = false;
    await flush(el);
  });
});
