import { LitElement, css, html, nothing } from "lit";
import { customElement, property, query, state } from "lit/decorators.js";

import {
  ApiError,
  ChatClient,
  safeStorage,
  visitorId,
  type Citation,
  type StoredMessage,
  type StreamEvent,
  type Turn,
  type WidgetSettings,
} from "./client";
import { direction, fill, lang2, strings, type Strings } from "./i18n";

/**
 * <nexiqon-chat agent="support" api-base="https://gateway.example.com" api-key="nxq_..."
 *               locale="en" accent="#0e8a7e" theme="auto" mode="floating"></nexiqon-chat>
 *
 * - W-00/W-01: streamed answers with citations, the pack's words, colour and theme (light, dark
 *   or the visitor's setting); floating launcher or inline on a help page.
 * - W-02: five languages, right-to-left, keyboard and screen-reader friendly (WCAG 2.2 AA).
 * - W-03: honest "not sure" answers with a one-tap handoff, confirmation cards for anything that
 *   changes data (a tap, never typed text), and an emailed copy of the conversation.
 * - W-04: rate answers and get suggested follow-up questions.
 *
 * Everything renders as text (never HTML) inside Shadow DOM, so neither host-page CSS nor anything
 * an answer contains can change the page.
 */

type Kind = "user" | "assistant" | "staff" | "notice";

interface Line {
  role: Kind;
  text: string;
  citations: Citation[];
  kind?: string;
  id?: string;
  unsure?: boolean;
  streaming?: boolean;
  rated?: "up" | "down";
  asking?: boolean; // the "what was missing?" box is open
}

const INK = "#12233f";

function luminance(hex: string): number | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const lin = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function ratio(a: number, b: number): number {
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/**
 * A theme colour with readable text on it (WCAG AA, 4.5:1): white or dark ink, whichever passes;
 * if neither does, the colour is darkened until white text passes (as Studio does for accents).
 */
export function readableTheme(hex: string): { accent: string; ink: string } | null {
  const lum = luminance(hex);
  if (lum === null) return null;
  const inkLum = luminance(INK)!;
  if (ratio(lum, 1) >= 4.5) return { accent: hex, ink: "#ffffff" };
  if (ratio(lum, inkLum) >= 4.5) return { accent: hex, ink: INK };
  const n = parseInt(hex.replace("#", ""), 16);
  let rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  let out = hex;
  for (let i = 0; i < 40; i++) {
    rgb = rgb.map((c) => c * 0.92);
    out = `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;
    if (ratio(luminance(out)!, 1) >= 4.5) break;
  }
  return { accent: out, ink: "#ffffff" };
}

function safeLink(uri: string | null | undefined): string | null {
  return uri && /^https?:\/\//i.test(uri) ? uri : null;
}

const norm = (q: string) => q.trim().toLowerCase().replace(/\s+/g, " ");

/** Up to ``n`` suggestions the visitor has not asked yet, in the pack's order. */
export function nextSuggestions(all: string[], asked: string[], n = 3): string[] {
  const seen = new Set(asked.map(norm));
  return all.filter((q) => !seen.has(norm(q))).slice(0, n);
}

/** An answer the assistant could not stand behind: abstained, or no answer to give. */
export function isUnsure(m: Pick<StoredMessage, "role" | "contract">): boolean {
  const c = m.contract ?? {};
  return m.role === "assistant" && !!c.abstained && !["handoff", "approval", "clarify", "declined"].includes(c.kind ?? "");
}

const ICON_UP = html`<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M2 21h4V9H2v12zm20-11a2 2 0 0 0-2-2h-6.3l1-4.6v-.3c0-.4-.2-.8-.4-1.1L13.2 1 6.6 7.6C6.2 8 6 8.5 6 9v10a2 2 0 0 0 2 2h9c.8 0 1.5-.5 1.8-1.2l3-7.1c.1-.2.2-.5.2-.7v-2z"/></svg>`;
const ICON_DOWN = html`<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M22 3h-4v12h4V3zM2 14a2 2 0 0 0 2 2h6.3l-1 4.6v.3c0 .4.2.8.4 1.1l1.1 1 6.6-6.6c.4-.4.6-.9.6-1.4V5a2 2 0 0 0-2-2H7c-.8 0-1.5.5-1.8 1.2l-3 7.1c-.1.2-.2.5-.2.7v2z"/></svg>`;

@customElement("nexiqon-chat")
export class NexiqonChat extends LitElement {
  static styles = css`
    :host {
      --nx-accent: #0e8a7e;
      --nx-on-accent: #ffffff;
      --nx-ink: #12233f;
      --nx-muted: #4f596b;
      --nx-surface: #ffffff;
      --nx-soft: #eef2f6;
      --nx-line: #c9d1db;
      --nx-warn: #8a4b00;
      --nx-warn-soft: #fff4e0;
      position: fixed;
      inset-inline-end: 16px;
      bottom: 16px;
      font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
      color: var(--nx-ink);
      z-index: 2147483000;
    }
    :host([data-theme="dark"]) {
      --nx-ink: #e8edf3;
      --nx-muted: #b3bccb;
      --nx-surface: #161c26;
      --nx-soft: #232c39;
      --nx-line: #3a4656;
      --nx-warn: #ffcf85;
      --nx-warn-soft: #3a2a12;
    }
    @media (prefers-color-scheme: dark) {
      :host(:not([data-theme="light"])) {
        --nx-ink: #e8edf3;
        --nx-muted: #b3bccb;
        --nx-surface: #161c26;
        --nx-soft: #232c39;
        --nx-line: #3a4656;
        --nx-warn: #ffcf85;
        --nx-warn-soft: #3a2a12;
      }
    }
    :host([mode="inline"]) {
      position: static;
      display: block;
      z-index: auto;
    }
    .sr {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }
    button {
      font: inherit;
      cursor: pointer;
      min-height: 32px;
    }
    button:focus-visible,
    textarea:focus-visible,
    input:focus-visible,
    a:focus-visible {
      outline: 3px solid var(--nx-accent);
      outline-offset: 2px;
    }
    .launcher {
      display: block;
      margin-inline-start: auto;
      background: var(--nx-accent);
      color: var(--nx-on-accent);
      border: 0;
      border-radius: 999px;
      padding: 12px 18px;
      box-shadow: 0 6px 18px rgb(18 35 63 / 0.25);
    }
    section {
      width: min(400px, calc(100vw - 32px));
      height: min(620px, calc(100vh - 96px));
      margin-bottom: 12px;
      background: var(--nx-surface);
      border: 1px solid var(--nx-line);
      border-radius: 14px;
      box-shadow: 0 16px 40px rgb(18 35 63 / 0.22);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    :host([mode="inline"]) section {
      width: 100%;
      height: var(--nx-height, 560px);
      margin: 0;
      box-shadow: none;
    }
    @media (prefers-reduced-motion: no-preference) {
      :host(:not([mode="inline"])) section {
        animation: rise 160ms ease-out;
      }
    }
    @keyframes rise {
      from {
        opacity: 0;
        transform: translateY(8px);
      }
    }
    header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 14px;
      background: var(--nx-accent);
      color: var(--nx-on-accent);
    }
    header h2 {
      font-size: 16px;
      margin: 0;
      flex: 1;
    }
    header button {
      background: transparent;
      color: inherit;
      border: 1px solid currentColor;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 13px;
    }
    header button[disabled] {
      opacity: 0.6;
      cursor: default;
    }
    .log {
      flex: 1;
      overflow-y: auto;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .turn {
      display: flex;
      flex-direction: column;
      gap: 4px;
      align-items: flex-start;
    }
    .msg {
      max-width: 85%;
      padding: 9px 12px;
      border-radius: 12px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .assistant {
      background: var(--nx-soft);
      align-self: flex-start;
    }
    .assistant.unsure {
      background: var(--nx-warn-soft);
      border: 1px solid var(--nx-warn);
    }
    .badge {
      display: inline-block;
      font-size: 12px;
      font-weight: 600;
      color: var(--nx-warn);
      margin-bottom: 2px;
    }
    .staff {
      background: var(--nx-surface);
      border: 2px solid var(--nx-accent);
      align-self: flex-start;
    }
    .who {
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: var(--nx-muted);
    }
    .user {
      background: var(--nx-accent);
      color: var(--nx-on-accent);
      align-self: flex-end;
    }
    .notice {
      white-space: normal;
      align-self: stretch;
      text-align: center;
      font-size: 13px;
      color: var(--nx-muted);
      background: transparent;
      max-width: none;
    }
    .streaming::after {
      content: "▍";
      opacity: 0.6;
    }
    .sources {
      white-space: normal;
      margin: 6px 0 0;
      padding: 6px 0 0;
      border-top: 1px solid var(--nx-line);
      font-size: 13px;
      list-style: none;
    }
    .sources a {
      color: inherit;
    }
    .rate {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 13px;
      color: var(--nx-muted);
    }
    .rate button {
      display: inline-grid;
      place-items: center;
      width: 32px;
      height: 32px;
      padding: 0;
      border: 1px solid transparent;
      border-radius: 8px;
      background: transparent;
      color: var(--nx-muted);
    }
    .rate button[aria-pressed="true"] {
      color: var(--nx-accent);
      border-color: var(--nx-accent);
    }
    :host([data-theme="dark"]) .rate button[aria-pressed="true"] {
      color: var(--nx-ink);
    }
    .why {
      display: flex;
      flex-direction: column;
      gap: 6px;
      width: 85%;
    }
    .status {
      font-size: 13px;
      color: var(--nx-muted);
      padding: 0 14px 6px;
      min-height: 18px;
    }
    .chips,
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .suggest {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .suggest h3 {
      margin: 0;
      font-size: 12px;
      font-weight: 600;
      color: var(--nx-muted);
    }
    .chips button,
    .actions button,
    .ghost {
      background: var(--nx-surface);
      color: var(--nx-ink);
      border: 1px solid var(--nx-accent);
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 13px;
    }
    .actions button.primary,
    .primary {
      background: var(--nx-accent);
      color: var(--nx-on-accent);
      border: 1px solid var(--nx-accent);
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 13px;
    }
    .card {
      border: 2px solid var(--nx-accent);
      border-radius: 12px;
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      background: var(--nx-surface);
    }
    .card h3 {
      margin: 0;
      font-size: 14px;
    }
    .card p {
      margin: 0;
      font-size: 13px;
      color: var(--nx-muted);
    }
    form.ask {
      display: flex;
      gap: 8px;
      padding: 10px;
      border-top: 1px solid var(--nx-line);
    }
    textarea,
    input {
      font: inherit;
      color: inherit;
      background: var(--nx-surface);
      border: 1px solid var(--nx-line);
      border-radius: 10px;
      padding: 8px 10px;
    }
    form.ask textarea {
      flex: 1;
      resize: none;
    }
    form.ask button {
      background: var(--nx-accent);
      color: var(--nx-on-accent);
      border: 0;
      border-radius: 10px;
      padding: 0 14px;
    }
    form.ask button[disabled] {
      opacity: 0.5;
      cursor: default;
    }
    footer {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 0 10px 10px;
      font-size: 13px;
    }
    .linkish {
      align-self: flex-start;
      background: none;
      border: 0;
      padding: 4px 0;
      color: var(--nx-muted);
      text-decoration: underline;
      font-size: 13px;
    }
    .mail {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }
    .mail input {
      flex: 1;
      min-width: 160px;
    }
    .note {
      color: var(--nx-muted);
      font-size: 12px;
      width: 100%;
    }
  `;

  @property() agent = "";
  @property({ attribute: "api-base" }) apiBase = "";
  @property({ attribute: "api-key" }) apiKey = "";
  @property() locale = "en";
  @property() accent = "";
  @property() label = "";
  @property({ reflect: true }) mode: "floating" | "inline" = "floating";
  @property() theme: "" | "auto" | "light" | "dark" = "";
  @state() open = false;
  @state() settings: WidgetSettings | null = null;
  @state() lines: Line[] = [];
  @state() status = "";
  @state() busy = false;
  @state() conversation: { id: string; status: string } | null = null;
  @state() pending: { purpose: string; prompt: string } | null = null;
  @state() failed = "";
  @state() announce = "";
  @state() mail: "closed" | "open" | "sending" = "closed";
  @state() mailNote = "";
  @query("textarea.input") input?: HTMLTextAreaElement;
  @query(".launcher") launcher?: HTMLButtonElement;

  client?: ChatClient;
  private loaded = false;
  private lastText = "";
  private poll?: ReturnType<typeof setInterval>;
  /** How often to look for a team member's reply while the conversation is with a person. */
  static pollMs = 8000;

  get t(): Strings {
    return strings(this.locale, this.settings?.labels ?? {});
  }

  get lang2(): string {
    return lang2(this.locale);
  }

  get inline(): boolean {
    return this.mode === "inline";
  }

  connectedCallback(): void {
    super.connectedCallback();
    this.addEventListener("keydown", this.onEscape);
    if (this.inline) void this.show();
  }

  disconnectedCallback(): void {
    this.removeEventListener("keydown", this.onEscape);
    this.stopPolling();
    super.disconnectedCallback();
  }

  protected updated(changed: Map<string, unknown>): void {
    if (changed.has("theme") || changed.has("settings")) this.applyMode();
    if (changed.has("conversation") || changed.has("open")) this.syncPolling();
  }

  /** While a person has the conversation, check for their replies (no socket needed). */
  private syncPolling(): void {
    const waiting = this.open && this.conversation?.status === "escalated";
    if (waiting && !this.poll) this.poll = setInterval(() => void this.refresh(), NexiqonChat.pollMs);
    if (!waiting) this.stopPolling();
  }

  private stopPolling(): void {
    if (this.poll) clearInterval(this.poll);
    this.poll = undefined;
  }

  async refresh(): Promise<void> {
    if (!this.conversation || this.busy) return;
    try {
      const past = await this.api().history(this.conversation.id);
      const known = new Set(this.lines.map((l) => l.id).filter(Boolean));
      const fresh = past.messages.filter((m) => !known.has(m.id) && m.role === "staff");
      if (!fresh.length) return;
      this.lines = [...this.lines, ...fresh.map((m) => this.line(m))];
      const last = fresh.at(-1)!;
      this.announce = `${this.t.team}: ${last.content}`;
      this.scrollDown();
    } catch {
      /* try again on the next tick */
    }
  }

  private onEscape = (e: KeyboardEvent): void => {
    if (e.key === "Escape" && this.open && !this.inline) {
      e.stopPropagation();
      void this.toggle();
    }
  };

  private storageKey(): string {
    return `nexiqon:conversation:${this.agent}`;
  }

  private api(): ChatClient {
    this.client ??= new ChatClient(this.apiBase, this.apiKey, this.agent, visitorId());
    return this.client;
  }

  private async show(): Promise<void> {
    this.open = true;
    await this.updateComplete;
    if (!this.loaded) await this.load();
  }

  async toggle(): Promise<void> {
    if (this.inline) return;
    this.open = !this.open;
    this.dispatchEvent(new CustomEvent("nexiqon-toggle", { detail: { open: this.open } }));
    await this.updateComplete;
    if (this.open) {
      this.input?.focus();
      if (!this.loaded) await this.load();
    } else {
      this.launcher?.focus(); // back where the visitor was (WCAG 2.4.3)
    }
  }

  private async load(): Promise<void> {
    this.loaded = true;
    if (!this.apiBase || !this.apiKey || !this.agent) return;
    try {
      this.settings = await this.api().settings(this.lang2);
      this.applyTheme();
      const saved = safeStorage()?.getItem(this.storageKey());
      if (saved) {
        const past = await this.api().history(saved);
        this.conversation = { id: past.id, status: past.status };
        this.lines = past.messages.map((m) => this.line(m));
        this.pending = this.pendingFrom(past.messages.at(-1) ?? null, past.status);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        safeStorage()?.removeItem(this.storageKey()); // that conversation is gone: start afresh
      } else {
        this.failed = this.t.unavailable;
      }
    }
  }

  private applyTheme(): void {
    const theme = readableTheme(this.accent || this.settings?.accent_color || "");
    if (!theme) return;
    this.style.setProperty("--nx-accent", theme.accent);
    this.style.setProperty("--nx-on-accent", theme.ink);
  }

  /** light / dark / auto: the page's attribute wins over the pack's setting. */
  private applyMode(): void {
    const mode = this.theme || this.settings?.theme || "auto";
    if (mode === "light" || mode === "dark") this.dataset.theme = mode;
    else delete this.dataset.theme;
  }

  private line(m: StoredMessage): Line {
    return {
      role: m.role as Kind,
      text: m.content,
      citations: m.contract?.citations ?? [],
      kind: m.contract?.kind,
      id: m.id,
      unsure: isUnsure(m),
    };
  }

  private pendingFrom(reply: StoredMessage | null, status: string): { purpose: string; prompt: string } | null {
    if (status !== "awaiting_approval" || !reply) return null;
    const i = reply.contract?.interrupt;
    return { purpose: i?.purpose ?? "action", prompt: i?.prompt || reply.content };
  }

  private async ensureConversation(): Promise<string> {
    if (this.conversation) return this.conversation.id;
    const c = await this.api().start(this.lang2);
    this.conversation = { id: c.id, status: c.status };
    safeStorage()?.setItem(this.storageKey(), c.id);
    return c.id;
  }

  private onEvent = (e: StreamEvent): void => {
    const last = this.lines.at(-1);
    if (e.event === "status") {
      const stage = String(e.data.stage ?? "");
      this.status = (this.t as unknown as Record<string, string>)[stage] ?? this.t.thinking;
    } else if (e.event === "tool" && e.data.status === "running") {
      this.status = fill(this.t.tool, { name: String(e.data.name ?? "") });
    } else if (e.event === "delta" && last?.streaming) {
      last.text += String(e.data.text ?? "");
      this.status = this.t.writing;
      this.lines = [...this.lines];
      this.scrollDown();
    }
  };

  private finish(turn: Turn): void {
    this.conversation = turn.conversation;
    const lines = this.lines.filter((l) => !l.streaming);
    if (turn.reply) {
      const reply = this.line(turn.reply);
      lines.push(reply);
      // One announcement per finished answer, not every streamed word (WCAG 4.1.3).
      const name = this.settings?.assistant_name ?? "";
      this.announce = fill(this.t.answered, { name, text: reply.unsure ? `${this.t.notSure}. ${reply.text}` : reply.text });
    }
    if (turn.conversation.status === "escalated") {
      lines.push({ role: "notice", text: this.t.withPerson, citations: [] });
    }
    this.lines = lines;
    this.pending = this.pendingFrom(turn.reply, turn.conversation.status);
    this.scrollDown();
  }

  async send(text: string): Promise<void> {
    const content = text.trim();
    if (!content || this.busy || this.pending) return;
    this.busy = true;
    this.failed = "";
    this.lastText = content;
    this.status = this.t.thinking;
    this.announce = "";
    this.lines = [
      ...this.lines,
      { role: "user", text: content, citations: [] },
      { role: "assistant", text: "", citations: [], streaming: true },
    ];
    if (this.input) this.input.value = "";
    this.scrollDown();
    try {
      const id = await this.ensureConversation();
      this.finish(await this.api().stream(id, content, this.onEvent));
    } catch {
      this.lines = this.lines.filter((l) => !l.streaming);
      this.failed = this.t.error;
    } finally {
      this.busy = false;
      this.status = "";
    }
  }

  private async act(run: (id: string) => Promise<Turn>, stage = ""): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.failed = "";
    this.status = stage || this.t.thinking;
    try {
      const id = await this.ensureConversation();
      this.finish(await run(id));
    } catch {
      this.failed = this.t.error;
    } finally {
      this.busy = false;
      this.status = "";
    }
  }

  decide(approved: boolean): Promise<void> {
    this.pending = null;
    return this.act((id) => this.api().approve(id, approved));
  }

  askForPerson(): Promise<void> {
    this.lines = [...this.lines, { role: "user", text: this.t.person, citations: [] }];
    return this.act((id) => this.api().handoff(id), this.t.handing_over);
  }

  async rate(line: Line, rating: "up" | "down", comment?: string): Promise<void> {
    if (!line.id) return;
    line.rated = rating;
    line.asking = rating === "down" && comment === undefined;
    this.lines = [...this.lines];
    try {
      if (comment !== undefined || rating === "up") await this.api().feedback(line.id, rating, comment);
    } catch {
      /* feedback is best effort: never interrupt the conversation for it */
    }
  }

  private async sendWhy(line: Line, form: HTMLFormElement): Promise<void> {
    const box = form.querySelector("textarea");
    line.asking = false;
    this.lines = [...this.lines];
    await this.rate(line, "down", box?.value.trim() || "");
    this.announce = this.t.thanks;
  }

  async emailCopy(address: string): Promise<void> {
    if (!this.conversation || this.mail === "sending") return;
    this.mail = "sending";
    try {
      await this.api().transcript(this.conversation.id, address.trim());
      this.closeMail();
      this.mailNote = this.t.emailSent;
    } catch (e) {
      this.mail = "open";
      const status = e instanceof ApiError ? e.status : 0;
      this.mailNote = status === 429 ? this.t.emailSoon : status === 400 || status === 422 ? this.t.emailBad : this.t.emailFailed;
    }
  }

  /** Close the email form and keep focus in the widget (the button that opened it). */
  private closeMail(): void {
    this.mail = "closed";
    void this.updateComplete.then(() => (this.renderRoot.querySelector(".linkish") as HTMLElement | null)?.focus());
  }

  private scrollDown(): void {
    void this.updateComplete.then(() => {
      const log = this.renderRoot.querySelector(".log");
      if (log) log.scrollTop = log.scrollHeight;
    });
  }

  private onKey(e: KeyboardEvent): void {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void this.send(this.input?.value ?? "");
    }
  }

  private canHandoff(): boolean {
    return this.settings?.handoff !== false && this.conversation?.status !== "escalated";
  }

  private renderRating(l: Line) {
    if (!l.id || l.streaming || l.unsure || this.settings?.feedback === false) return nothing;
    if (!["grounded", "smalltalk", undefined].includes(l.kind)) return nothing;
    const t = this.t;
    return html`<div class="rate" role="group" aria-label=${`${t.helpful} / ${t.notHelpful}`}>
        <button aria-label=${t.helpful} aria-pressed=${String(l.rated === "up")} @click=${() => this.rate(l, "up")}>${ICON_UP}</button>
        <button aria-label=${t.notHelpful} aria-pressed=${String(l.rated === "down")} @click=${() => this.rate(l, "down")}>${ICON_DOWN}</button>
        ${l.rated && !l.asking ? html`<span>${t.thanks}</span>` : nothing}
      </div>
      ${l.asking
        ? html`<form class="why" @submit=${(e: Event) => (e.preventDefault(), this.sendWhy(l, e.target as HTMLFormElement))}>
            <label class="sr" for=${`why-${l.id}`}>${t.whatWasMissing}</label>
            <textarea id=${`why-${l.id}`} rows="2" maxlength="2000" placeholder=${t.whatWasMissing}></textarea>
            <button class="ghost" type="submit">${t.sendFeedback}</button>
          </form>`
        : nothing}`;
  }

  private renderLine(l: Line) {
    const t = this.t;
    const cls = `msg ${l.role}${l.streaming ? " streaming" : ""}${l.unsure ? " unsure" : ""}`;
    // No whitespace between the tags: .msg keeps the answer's own line breaks (pre-wrap), so any
    // template indentation inside the bubble would show as blank space.
    const sources = l.citations.length
      ? html`<ul class="sources" aria-label=${t.sources}>${l.citations.map((c) => {
          const href = safeLink(c.source_uri);
          const label = href ? html`<a href=${href} target="_blank" rel="noopener noreferrer">${c.citation}</a>` : c.citation;
          return html`<li>[${c.marker}] ${label}</li>`;
        })}</ul>`
      : nothing;
    const badge = l.unsure ? html`<span class="badge">${t.notSure}</span><br />` : nothing;
    const bubble = html`<div class=${cls} aria-hidden=${l.streaming ? "true" : "false"}>${badge}${l.text}${sources}</div>`;
    if (l.role === "staff") {
      return html`<div class="msg staff"><span class="who">${this.t.team}</span>${l.text}</div>`;
    }
    if (l.role !== "assistant") return bubble;
    return html`<div class="turn">
      ${bubble}
      ${l.unsure && !l.streaming && this.canHandoff() && l === this.lines.at(-1)
        ? html`<button class="ghost" @click=${() => this.askForPerson()} ?disabled=${this.busy}>${t.askPerson}</button>`
        : nothing}
      ${this.renderRating(l)}
    </div>`;
  }

  /** Anything that changes data waits for a tap on this card; typing "yes" does nothing. */
  private renderPending() {
    if (!this.pending || this.busy) return nothing;
    const t = this.t;
    const handoff = this.pending.purpose === "handoff";
    return html`<div class="card" role="group" aria-labelledby="confirm-title">
      <h3 id="confirm-title">${t.confirmTitle}</h3>
      <p>${t.confirmHelp}</p>
      <div class="actions">
        <button class="primary" @click=${() => this.decide(true)}>${handoff ? t.sendToTeam : t.yes}</button>
        <button @click=${() => this.decide(false)}>${handoff ? t.notNow : t.no}</button>
      </div>
    </div>`;
  }

  private renderSuggestions() {
    const s = this.settings;
    const last = this.lines.at(-1);
    if (!s || this.busy || this.pending || last?.role !== "assistant" || last.streaming) return nothing;
    if (this.conversation?.status === "escalated") return nothing;
    const asked = this.lines.filter((l) => l.role === "user").map((l) => l.text);
    const next = nextSuggestions(s.suggestions ?? s.starter_questions ?? [], asked);
    if (!next.length) return nothing;
    return html`<div class="suggest">
      <h3 id="suggest-title">${this.t.suggested}</h3>
      <div class="chips" role="group" aria-labelledby="suggest-title">
        ${next.map((q) => html`<button @click=${() => this.send(q)}>${q}</button>`)}
      </div>
    </div>`;
  }

  private renderMail() {
    const t = this.t;
    const s = this.settings;
    const said = this.lines.some((l) => l.role === "assistant" && !l.streaming);
    if (s?.transcript_email === false || !this.conversation || !said) return nothing;
    return html`<footer>
      ${this.mail === "closed"
        ? html`<button class="linkish" @click=${() => ((this.mail = "open"), (this.mailNote = ""))}>${t.emailCopy}</button>`
        : html`<form class="mail" @submit=${(e: Event) => (e.preventDefault(), this.emailCopy(((e.target as HTMLFormElement).elements.namedItem("email") as HTMLInputElement).value))}>
            <label class="sr" for="nx-email">${t.emailLabel}</label>
            <input id="nx-email" name="email" type="email" autocomplete="email" required maxlength="320" placeholder=${t.emailLabel} />
            <button class="primary" type="submit" ?disabled=${this.mail === "sending"}>${t.emailSend}</button>
            <button class="ghost" type="button" @click=${() => this.closeMail()}>${t.emailCancel}</button>
            <span class="note">${t.emailNote}</span>
          </form>`}
      ${this.mailNote ? html`<span role="status">${this.mailNote}</span>` : nothing}
    </footer>`;
  }

  render() {
    const t = this.t;
    const s = this.settings;
    const title = s?.title ?? (this.label || t.open);
    const escalated = this.conversation?.status === "escalated";
    const empty = !this.lines.length;
    return html`
      ${this.open
        ? html`<section
            role=${this.inline ? "region" : "dialog"}
            aria-label=${title}
            dir=${direction(this.locale)}
            lang=${this.lang2}
          >
            <header>
              <h2>${title}</h2>
              ${s?.handoff !== false
                ? html`<button @click=${() => this.askForPerson()} ?disabled=${escalated || this.busy || !!this.pending}>
                    ${t.person}
                  </button>`
                : nothing}
              ${this.inline ? nothing : html`<button @click=${this.toggle} aria-label=${t.close}>✕</button>`}
            </header>
            <div class="log" role="log" aria-busy=${String(this.busy)}>
              ${s?.greeting ? html`<div class="msg assistant">${s.greeting}</div>` : nothing}
              ${empty && s?.starter_questions?.length
                ? html`<div class="chips">${s.starter_questions.map((q) => html`<button @click=${() => this.send(q)}>${q}</button>`)}</div>`
                : nothing}
              ${this.lines.map((l) => this.renderLine(l))} ${this.renderPending()} ${this.renderSuggestions()}
              ${this.failed
                ? html`<div class="msg notice" role="alert">
                    ${this.failed}
                    ${this.lastText ? html` <button class="ghost" @click=${() => this.send(this.lastText)}>${t.retry}</button>` : nothing}
                  </div>`
                : nothing}
            </div>
            <div class="status" aria-live="polite">${this.status}</div>
            <div class="sr" aria-live="polite" aria-atomic="true">${this.announce}</div>
            <form class="ask" @submit=${(e: Event) => (e.preventDefault(), this.send(this.input?.value ?? ""))}>
              <textarea
                class="input"
                rows="2"
                maxlength="8000"
                aria-label=${t.placeholder}
                placeholder=${t.placeholder}
                @keydown=${this.onKey}
                ?disabled=${!!this.pending}
              ></textarea>
              <button type="submit" ?disabled=${this.busy || !!this.pending}>${t.send}</button>
            </form>
            ${this.renderMail()}
          </section>`
        : nothing}
      ${this.inline
        ? nothing
        : html`<button class="launcher" aria-expanded=${String(this.open)} @click=${this.toggle}>
            ${this.open ? t.close : this.label || s?.title || t.open}
          </button>`}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "nexiqon-chat": NexiqonChat;
  }
}
