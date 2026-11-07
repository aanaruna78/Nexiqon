import { LitElement, css, html } from "lit";
import { customElement, property, state } from "lit/decorators.js";

/**
 * <nexiqon-chat agent="..." api-base="https://..."></nexiqon-chat>
 *
 * Phase 0 skeleton: launcher + panel shell in Shadow DOM so host-page CSS cannot leak in.
 * Streaming answers, citations and handoff arrive with W-00 (Phase 3).
 */
@customElement("nexiqon-chat")
export class NexiqonChat extends LitElement {
  static styles = css`
    :host {
      --nx-accent: #0e8a7e;
      --nx-ink: #12233f;
      position: fixed;
      right: 16px;
      bottom: 16px;
      font-family: system-ui, sans-serif;
      z-index: 2147483000;
    }
    button.launcher {
      background: var(--nx-accent);
      color: #fff;
      border: 0;
      border-radius: 999px;
      padding: 12px 18px;
      font-size: 15px;
      cursor: pointer;
    }
    button.launcher:focus-visible {
      outline: 3px solid var(--nx-ink);
      outline-offset: 2px;
    }
    section {
      width: min(380px, calc(100vw - 32px));
      height: min(560px, calc(100vh - 96px));
      margin-bottom: 12px;
      background: #fff;
      color: var(--nx-ink);
      border-radius: 12px;
      box-shadow: 0 12px 32px rgb(18 35 63 / 0.2);
      display: flex;
      flex-direction: column;
      padding: 16px;
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
  `;

  @property() agent = "";
  @property({ attribute: "api-base" }) apiBase = "";
  @property() label = "Ask a question";
  @state() open = false;

  toggle(): void {
    this.open = !this.open;
    this.dispatchEvent(new CustomEvent("nexiqon-toggle", { detail: { open: this.open } }));
  }

  render() {
    return html`
      ${this.open
        ? html`<section role="dialog" aria-label=${this.label}>
            <p>Nexiqon assistant${this.agent ? html` · <code>${this.agent}</code>` : ""}</p>
          </section>`
        : ""}
      <button class="launcher" aria-expanded=${String(this.open)} @click=${this.toggle}>
        ${this.open ? "Close" : this.label}
      </button>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "nexiqon-chat": NexiqonChat;
  }
}
