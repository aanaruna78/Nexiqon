/**
 * Talks to the Nexiqon gateway for the widget: channel settings, conversations, streamed turns.
 *
 * The widget key is public by design (it only works from the origins it is issued for, and only
 * as an end user). Each visitor gets a random id kept in localStorage, so visitors never share
 * conversations. Platform tokens never reach the browser: the gateway exchanges the key itself.
 */

export interface WidgetSettings {
  agent: string;
  locale: string;
  title: string;
  assistant_name: string;
  greeting: string | null;
  starter_questions: string[];
  accent_color: string | null;
  handoff: boolean;
}

export interface Citation {
  marker: string;
  citation: string;
  source_uri?: string | null;
}

export interface Contract {
  kind?: string;
  status?: string;
  citations?: Citation[];
  abstained?: boolean;
  interrupt?: { kind?: string; purpose?: string; prompt?: string };
}

export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  contract: Contract;
}

export interface Conversation {
  id: string;
  status: string;
}

export interface Turn {
  conversation: Conversation;
  user_message: StoredMessage | null;
  reply: StoredMessage | null;
}

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const VISITOR_KEY = "nexiqon:visitor";

/** A random, URL-safe id of 32 characters (what identity accepts as a visitor id). */
export function newVisitorId(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

export function visitorId(storage: Storage | undefined = safeStorage()): string {
  try {
    const existing = storage?.getItem(VISITOR_KEY);
    if (existing && /^[A-Za-z0-9_-]{22,64}$/.test(existing)) return existing;
    const id = newVisitorId();
    storage?.setItem(VISITOR_KEY, id);
    return id;
  } catch {
    return newVisitorId(); // storage blocked: a fresh visitor for this page view
  }
}

export function safeStorage(): Storage | undefined {
  try {
    return globalThis.localStorage;
  } catch {
    return undefined;
  }
}

/** Server-sent events from a fetch body: yields {event, data} per block. */
export async function* parseSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const parsed = parseBlock(block);
      if (parsed) yield parsed;
    }
    if (done) {
      const last = parseBlock(buffer);
      if (last) yield last;
      return;
    }
  }
}

function parseBlock(block: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

export class ChatClient {
  constructor(
    readonly apiBase: string,
    readonly apiKey: string,
    readonly agent: string,
    readonly visitor: string,
    readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  private headers(json = false): Record<string, string> {
    return {
      authorization: `Bearer ${this.apiKey}`,
      "x-nexiqon-visitor": this.visitor,
      ...(json ? { "content-type": "application/json" } : {}),
    };
  }

  private url(path: string): string {
    return `${this.apiBase.replace(/\/$/, "")}${path}`;
  }

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const r = await this.fetchImpl(this.url(path), {
      method,
      headers: this.headers(body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) throw new ApiError(r.status, await problem(r));
    return (await r.json()) as T;
  }

  settings(locale: string): Promise<WidgetSettings> {
    const q = encodeURIComponent(locale);
    return this.call("GET", `/channel/v1/channels/widget/agents/${this.agent}?locale=${q}`);
  }

  start(locale: string): Promise<Conversation> {
    return this.call("POST", "/conversation/v1/conversations", {
      agent: this.agent,
      channel: "widget",
      locale,
    });
  }

  history(id: string): Promise<Conversation & { messages: StoredMessage[] }> {
    return this.call("GET", `/conversation/v1/conversations/${id}`);
  }

  approve(id: string, approved: boolean): Promise<Turn> {
    return this.call("POST", `/conversation/v1/conversations/${id}/approval`, { approved });
  }

  handoff(id: string): Promise<Turn> {
    return this.call("POST", `/conversation/v1/conversations/${id}/handoff`);
  }

  /** Sends a message; ``onEvent`` sees status, sources, tool and delta events; resolves with the
   *  stored turn (whose reply replaces the streamed text: it carries the checked citations). */
  async stream(id: string, content: string, onEvent: (e: StreamEvent) => void): Promise<Turn> {
    const r = await this.fetchImpl(this.url(`/conversation/v1/conversations/${id}/messages/stream`), {
      method: "POST",
      headers: { ...this.headers(true), accept: "text/event-stream" },
      body: JSON.stringify({ content }),
    });
    if (!r.ok || !r.body) throw new ApiError(r.status, await problem(r));
    for await (const e of parseSSE(r.body)) {
      if (e.event === "message") return e.data as unknown as Turn;
      if (e.event === "error") throw new ApiError(502, String(e.data.detail ?? "stream failed"));
      onEvent(e);
    }
    throw new ApiError(502, "The answer stream ended early");
  }
}

async function problem(r: Response): Promise<string> {
  try {
    const body = (await r.json()) as { detail?: string; title?: string };
    return body.detail || body.title || r.statusText;
  } catch {
    return r.statusText || `HTTP ${r.status}`;
  }
}
