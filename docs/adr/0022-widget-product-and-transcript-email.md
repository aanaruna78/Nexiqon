# ADR 0022: Widget product and transcript email

Status: Accepted (2026-11-19)

## Context

W-01 to W-04 turn the Phase 3 widget into something a customer can put on their site:
- their own words;
- light and dark themes;
- inline or floating;
- accessible in several languages;
- honest when unsure;
- safe confirmations;
- feedback and follow-ups;
- an emailed copy of the conversation.

Email is the risky part. The widget key is public, so whatever it can trigger, anyone can.

## Decision

- **Pack-driven presentation.**
  - The pack's `channels.widget`, and an assistant's own `widget` settings, define:
    - `labels` per locale (`open`, `placeholder`, `person`, `sources`, `send`);
    - `theme` (`auto`, `light` or `dark`);
    - `feedback` and `transcript_email` switches.
  - `sources` falls back to `vocabulary.knowledge_source`.
  - The channel service also returns `suggestions`: starter questions, then English intent
    examples, for English only.
  - Page attributes (`theme`, `accent`, `mode`) override the pack.
- **Honest uncertainty and confirmations live in the widget.**
  - An abstained answer is marked "Not sure" and offers a one-tap handoff.
  - Approvals render as a card, and the message box is disabled until the visitor taps. No
    language detection: typed "yes" never confirms.
- **Accessibility.**
  - The answer log is `role="log"`, and the streaming bubble is hidden from assistive technology.
    One polite announcement is made per finished answer.
  - Esc closes the widget and returns focus to the launcher. Focus never falls back to the page
    when a control inside the widget disappears.
  - Targets are at least 32 px.
  - Studio's end-to-end suite runs axe on the live widget in light, dark and Arabic.
  - The manual screen-reader walkthrough is in `docs/guides/widget-accessibility.md`.
- **Size budget.** The build fails above 60 KB gzipped (`scripts/check-size.mjs`); it is about
  18 KB today.
- **Transcript email goes through two services, and never directly from the browser.**
  - The widget calls conversation `POST /v1/conversations/{id}/transcript`.
    - Only the conversation's own participant may call it: staff see conversations in Studio,
      but they do not mail them.
    - Each conversation has a 10-minute cooldown.
    - The body is plain text and holds only what the visitor saw: questions, answers and
      citations.
  - Conversation then calls notification `POST /v1/emails` as its **own identity**
    (`conversation_identity`, ADR 0017). Its role grants nothing but `notification.email.send`.
  - That action is `service_only` in the policy, so a person, an owner or a widget key can never
    send email directly. Otherwise the public key would make the platform an open relay.
  - Notification enforces two ceilings: at most 3 emails per recipient per hour, so one inbox
    cannot be flooded through many conversations, and an hourly ceiling per organization.
  - It validates single, one-line addresses and subjects (no header injection).
  - It logs each delivery with a **hash** of the address, never the address or the body.
  - Events carry ids only: the audit service records every event, so transcripts and addresses
    must never be in them.
- **Email port.** Notification sends through an `EmailSender` port.
  - `smtp` is a standard-library adapter run in a worker thread.
  - `memory` is for tests and installs without a relay; it is the chart default until a relay is
    configured.
  - The local stack sends to Mailpit (http://localhost:8025).

## Consequences

- Customers can embed the widget in plain HTML, React or WordPress (there is a plugin under
  `frontend/apps/widget/integrations/wordpress`).
- Conversation now holds a signing key, mounted only in the agent group.
- Email for other purposes (budget alerts, approvals) reuses the same notification endpoint and
  limits, under their own `kind`. Webhooks and in-app notifications remain NT-01 follow-ups.
