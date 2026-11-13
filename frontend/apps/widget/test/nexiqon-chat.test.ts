import "../src/nexiqon-chat";
import { ChatClient, parseSSE, visitorId } from "../src/client";
import { readableTheme, type NexiqonChat } from "../src/nexiqon-chat";

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
