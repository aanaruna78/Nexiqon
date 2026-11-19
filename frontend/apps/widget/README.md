# @nexiqon/widget

The embeddable chat widget: a Web Component in Shadow DOM, about 18 KB gzipped. The build fails
above the 60 KB budget (`scripts/check-size.mjs`). Studio serves the built file at
`/widget/nexiqon-chat.js`.

## Embed it

Create a widget key for your site in Studio (assistant → Widget). The key only works from the
origins you list, and only as an end user.

### Plain HTML

```html
<script type="module" src="https://<studio>/widget/nexiqon-chat.js"></script>
<nexiqon-chat agent="support" api-base="https://<gateway>" api-key="nxq_..." locale="en"></nexiqon-chat>
```

### React (or any framework)

Load the script once, then use the tag. React 19 passes the attributes as they are. In React 18,
use lowercase attribute names, as below.

```tsx
import { useEffect } from "react";

export function Help() {
  useEffect(() => {
    if (!customElements.get("nexiqon-chat")) {
      const s = document.createElement("script");
      s.type = "module";
      s.src = "https://<studio>/widget/nexiqon-chat.js";
      document.head.appendChild(s);
    }
  }, []);
  return <nexiqon-chat agent="support" api-base="https://<gateway>" api-key="nxq_..." mode="inline" />;
}
```

### WordPress

Install `integrations/wordpress/nexiqon-chat.php` as a plugin. In **Settings → Nexiqon Chat**,
enter the script URL, gateway, assistant and key. Then either:

- tick "Show the floating chat button", or
- put `[nexiqon_chat]` on a page for an inline chat.

## Attributes

| Attribute | Meaning |
|---|---|
| `agent` | The assistant's name |
| `api-base` | The gateway URL |
| `api-key` | The widget key (public by design) |
| `locale` | `en`, `es`, `fr`, `de` or `ar` (others fall back to English; `he`, `fa` and `ur` lay out right to left) |
| `mode` | `floating` (a launcher button, the default) or `inline` (always open, fills its container; height from `--nx-height`) |
| `theme` | `auto` (the visitor's system setting), `light` or `dark`. Overrides the pack's `channels.widget.theme`. |
| `accent` | A `#rrggbb` colour. Overrides the pack's; the text colour on it is chosen for 4.5:1 contrast. |
| `label` | The launcher text |

## What visitors get

- **Answers with sources.** Answers stream in with progress ("Searching the documentation…").
  The stored reply then replaces the streamed text and adds its verified citations. Everything is
  rendered as text, never HTML. Source links open only for `http(s)` URLs, with
  `rel="noopener noreferrer"`.
- **Honest uncertainty.** When the assistant cannot stand behind an answer, the answer is marked
  "Not sure" and offers "Ask a person instead" in one tap.
- **Confirmation cards.** Anything that changes data waits for a tap on a card. Typing "yes" does
  nothing, and the message box is disabled until the visitor chooses.
- **Talk to a person.** In the header, at any time. It is renamed by the pack's
  `channels.widget.labels.person`, e.g. "Contact support".
- **Feedback.** Thumbs up or down on each answer. "Not helpful" asks what was missing (optional).
  Ratings are stored by the conversation service and emitted as
  `nexiqon.conversation.feedback.given` events for metering and insights.
- **Suggested questions.** After each answer, up to three questions the visitor has not asked yet:
  the pack's starter questions, then its example questions (for English).
- **Email me a copy.** Sends the conversation to an address the visitor gives:
  - only for their own conversation;
  - through the notification service;
  - one copy per conversation every 10 minutes, and at most 3 an hour to one address.

  The address is not stored. The pack can turn this off with `channels.widget.transcript_email`.

## The pack's words (W-01)

`channels.widget.labels` (per locale) renames `open`, `placeholder`, `person`, `sources` and
`send`. When `sources` is not given, the pack's `vocabulary.knowledge_source` is used, e.g.
"Product documentation". An assistant's own `widget` settings override the pack's, field by field.

## Accessibility (W-02, WCAG 2.2 AA)

- The chat is a labelled dialog (or a region, inline). The log is `role="log"`.
- Each finished answer is announced once to screen readers, not every streamed word.
- **Esc** closes the floating chat and returns focus to the launcher.
- All controls are buttons with visible focus rings and targets of at least 32 px.
- Colours meet AA in light and dark. Motion is off for visitors who prefer reduced motion.

The screen-reader walkthrough is in `docs/guides/widget-accessibility.md`. Studio's end-to-end
suite runs an automated axe scan of the live widget in light, dark and Arabic.

```bash
pnpm --filter @nexiqon/widget test
pnpm --filter @nexiqon/widget build   # dist/nexiqon-chat.js, checked against the size budget
```
