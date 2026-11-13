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

/**
 * <nexiqon-chat agent="support" api-base="https://gateway.example.com" api-key="nxq_..."
 *               locale="en" accent="#0e8a7e"></nexiqon-chat>
 *
 * W-00: streamed answers with citations, approvals, a "talk to a person" button and the pack's
 * theme colour. Everything renders as text (never HTML) inside Shadow DOM, so neither host-page
 * CSS nor anything an answer contains can change the page.
 */

type Kind = "user" | "assistant" | "notice";

interface Line {
  role: Kind;
  text: string;
  citations: Citation[];
  kind?: string;
  streaming?: boolean;
}

const STRINGS = {
  en: {
    open: "Ask a question",
    close: "Close chat",
    placeholder: "Type your question",
    send: "Send",
    person: "Talk to a person",
    sources: "Sources",
    yes: "Yes, go ahead",
    no: "No, thanks",
    sendToTeam: "Send to the team",
    notNow: "Not now",
    withPerson: "A person from the team will pick this up here.",
    thinking: "Thinking…",
    searching: "Searching the documentation…",
    writing: "Writing…",
    handing_over: "Preparing a summary for the team…",
    tool: "Checking {name}…",
    error: "Something went wrong. Please try again.",
    unavailable: "The assistant isn't available right now.",
    retry: "Try again",
  },
  es: {
    open: "Haz una pregunta",
    close: "Cerrar chat",
    placeholder: "Escribe tu pregunta",
    send: "Enviar",
    person: "Hablar con una persona",
    sources: "Fuentes",
    yes: "Sí, adelante",
    no: "No, gracias",
    sendToTeam: "Enviar al equipo",
    notNow: "Ahora no",
    withPerson: "Una persona del equipo continuará aquí.",
    thinking: "Pensando…",
    searching: "Buscando en la documentación…",
    writing: "Escribiendo…",
    handing_over: "Preparando un resumen para el equipo…",
    tool: "Consultando {name}…",
    error: "Algo salió mal. Inténtalo de nuevo.",
    unavailable: "El asistente no está disponible ahora.",
    retry: "Reintentar",
  },
  ar: {
    open: "اطرح سؤالًا",
    close: "إغلاق المحادثة",
    placeholder: "اكتب سؤالك",
    send: "إرسال",
    person: "التحدث إلى شخص",
    sources: "المصادر",
    yes: "نعم، تابع",
    no: "لا، شكرًا",
    sendToTeam: "أرسل إلى الفريق",
    notNow: "ليس الآن",
    withPerson: "سيتابع أحد أعضاء الفريق هنا.",
    thinking: "جارٍ التفكير…",
    searching: "جارٍ البحث في الوثائق…",
    writing: "جارٍ الكتابة…",
    handing_over: "جارٍ إعداد ملخص للفريق…",
    tool: "جارٍ التحقق من {name}…",
    error: "حدث خطأ ما. حاول مرة أخرى.",
    unavailable: "المساعد غير متاح الآن.",
    retry: "إعادة المحاولة",
  },
} as const;
type Strings = { [K in keyof (typeof STRINGS)["en"]]: string };

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

@customElement("nexiqon-chat")
export class NexiqonChat extends LitElement {
  static styles = css`
    :host {
      --nx-accent: #0e8a7e;
      --nx-on-accent: #ffffff;
      --nx-ink: #12233f;
      --nx-muted: #5a6478;
      --nx-surface: #ffffff;
      --nx-soft: #f2f5f8;
      --nx-line: #dfe4ea;
      position: fixed;
      inset-inline-end: 16px;
      bottom: 16px;
      font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
      color: var(--nx-ink);
      z-index: 2147483000;
    }
    @media (prefers-color-scheme: dark) {
      :host {
        --nx-ink: #e8edf3;
        --nx-muted: #a5afbf;
        --nx-surface: #161c26;
        --nx-soft: #222a36;
        --nx-line: #303a48;
      }
    }
    button {
      font: inherit;
      cursor: pointer;
    }
    button:focus-visible,
    textarea:focus-visible,
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
      height: min(600px, calc(100vh - 96px));
      margin-bottom: 12px;
      background: var(--nx-surface);
      border: 1px solid var(--nx-line);
      border-radius: 14px;
      box-shadow: 0 16px 40px rgb(18 35 63 / 0.22);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    @media (prefers-reduced-motion: no-preference) {
      section {
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
    .user {
      background: var(--nx-accent);
      color: var(--nx-on-accent);
      align-self: flex-end;
    }
    .notice {
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
      margin: 6px 0 0;
      padding: 6px 0 0;
      border-top: 1px solid var(--nx-line);
      font-size: 13px;
      list-style: none;
    }
    .sources a {
      color: inherit;
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
    .chips button,
    .actions button {
      background: var(--nx-surface);
      color: var(--nx-ink);
      border: 1px solid var(--nx-accent);
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 13px;
    }
    .actions button.primary {
      background: var(--nx-accent);
      color: var(--nx-on-accent);
    }
    form {
      display: flex;
      gap: 8px;
      padding: 10px;
      border-top: 1px solid var(--nx-line);
    }
    textarea {
      flex: 1;
      resize: none;
      font: inherit;
      color: inherit;
      background: var(--nx-surface);
      border: 1px solid var(--nx-line);
      border-radius: 10px;
      padding: 8px 10px;
    }
    form button {
      background: var(--nx-accent);
      color: var(--nx-on-accent);
      border: 0;
      border-radius: 10px;
      padding: 0 14px;
    }
    form button[disabled] {
      opacity: 0.5;
      cursor: default;
    }
  `;

  @property() agent = "";
  @property({ attribute: "api-base" }) apiBase = "";
  @property({ attribute: "api-key" }) apiKey = "";
  @property() locale = "en";
  @property() accent = "";
  @property() label = "";
  @state() open = false;
  @state() settings: WidgetSettings | null = null;
  @state() lines: Line[] = [];
  @state() status = "";
  @state() busy = false;
  @state() conversation: { id: string; status: string } | null = null;
  @state() pending: { purpose: string } | null = null;
  @state() failed = "";
  @query("textarea") input?: HTMLTextAreaElement;

  client?: ChatClient;
  private loaded = false;
  private lastText = "";

  get t(): Strings {
    return (STRINGS as Record<string, Strings>)[this.lang2] ?? STRINGS.en;
  }

  get lang2(): string {
    return (this.locale || "en").slice(0, 2);
  }

  private storageKey(): string {
    return `nexiqon:conversation:${this.agent}`;
  }

  private api(): ChatClient {
    this.client ??= new ChatClient(this.apiBase, this.apiKey, this.agent, visitorId());
    return this.client;
  }

  async toggle(): Promise<void> {
    this.open = !this.open;
    this.dispatchEvent(new CustomEvent("nexiqon-toggle", { detail: { open: this.open } }));
    if (this.open) {
      await this.updateComplete;
      this.input?.focus();
      if (!this.loaded) await this.load();
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

  private line(m: StoredMessage): Line {
    return {
      role: m.role,
      text: m.content,
      citations: m.contract?.citations ?? [],
      kind: m.contract?.kind,
    };
  }

  private pendingFrom(reply: StoredMessage | null, status: string): { purpose: string } | null {
    if (status !== "awaiting_approval" || !reply) return null;
    return { purpose: reply.contract?.interrupt?.purpose ?? "action" };
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
      this.status = (this.t as Record<string, string>)[stage] ?? this.t.thinking;
    } else if (e.event === "tool" && e.data.status === "running") {
      this.status = this.t.tool.replace("{name}", String(e.data.name ?? ""));
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
    if (turn.reply) lines.push(this.line(turn.reply));
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

  private renderLine(l: Line) {
    const cls = `msg ${l.role}${l.streaming ? " streaming" : ""}`;
    return html`<div class=${cls}>
      ${l.text}
      ${l.citations.length
        ? html`<ul class="sources" aria-label=${this.t.sources}>
            ${l.citations.map((c) => {
              const href = safeLink(c.source_uri);
              return html`<li>
                [${c.marker}]
                ${href
                  ? html`<a href=${href} target="_blank" rel="noopener noreferrer">${c.citation}</a>`
                  : c.citation}
              </li>`;
            })}
          </ul>`
        : nothing}
    </div>`;
  }

  private renderPending() {
    if (!this.pending || this.busy) return nothing;
    const handoff = this.pending.purpose === "handoff";
    return html`<div class="actions" role="group">
      <button class="primary" @click=${() => this.decide(true)}>
        ${handoff ? this.t.sendToTeam : this.t.yes}
      </button>
      <button @click=${() => this.decide(false)}>${handoff ? this.t.notNow : this.t.no}</button>
    </div>`;
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
            role="dialog"
            aria-label=${title}
            dir=${this.lang2 === "ar" ? "rtl" : "ltr"}
            lang=${this.lang2}
          >
            <header>
              <h2>${title}</h2>
              ${s?.handoff !== false
                ? html`<button
                    @click=${() => this.askForPerson()}
                    ?disabled=${escalated || this.busy || !!this.pending}
                  >
                    ${t.person}
                  </button>`
                : nothing}
              <button @click=${this.toggle} aria-label=${t.close}>✕</button>
            </header>
            <div class="log" aria-live="polite" aria-busy=${String(this.busy)}>
              ${s?.greeting ? html`<div class="msg assistant">${s.greeting}</div>` : nothing}
              ${empty && s?.starter_questions?.length
                ? html`<div class="chips">
                    ${s.starter_questions.map(
                      (q) => html`<button @click=${() => this.send(q)}>${q}</button>`,
                    )}
                  </div>`
                : nothing}
              ${this.lines.map((l) => this.renderLine(l))} ${this.renderPending()}
              ${this.failed
                ? html`<div class="msg notice" role="alert">
                    ${this.failed}
                    ${this.lastText
                      ? html` <button @click=${() => this.send(this.lastText)}>${t.retry}</button>`
                      : nothing}
                  </div>`
                : nothing}
            </div>
            <div class="status" aria-live="polite">${this.status}</div>
            <form @submit=${(e: Event) => (e.preventDefault(), this.send(this.input?.value ?? ""))}>
              <textarea
                rows="2"
                maxlength="8000"
                aria-label=${t.placeholder}
                placeholder=${t.placeholder}
                @keydown=${this.onKey}
                ?disabled=${!!this.pending}
              ></textarea>
              <button type="submit" ?disabled=${this.busy || !!this.pending}>${t.send}</button>
            </form>
          </section>`
        : nothing}
      <button class="launcher" aria-expanded=${String(this.open)} @click=${this.toggle}>
        ${this.open ? t.close : this.label || s?.title || t.open}
      </button>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "nexiqon-chat": NexiqonChat;
  }
}
