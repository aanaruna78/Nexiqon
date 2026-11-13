# @nexiqon/widget

The embeddable chat widget (W-00): a Web Component in Shadow DOM, about 13 KB gzipped.

```html
<!-- dist/nexiqon-chat.js, served from any static host or CDN -->
<script type="module" src="https://<static-host>/nexiqon-chat.js"></script>
<nexiqon-chat agent="support" api-base="https://<gateway>" api-key="nxq_..." locale="en"></nexiqon-chat>
```

- **Key and visitors.** The widget key is public by design. It only works from the origins it was
  issued for, and only as an end user. Each visitor gets a random id in `localStorage`
  (`X-Nexiqon-Visitor`), so visitors never see each other's conversations. The conversation id is
  remembered per agent, so a reload continues the conversation.
- **What the user sees.**
  - The title, greeting, starter questions and theme colour come from the pack's
    `channels.widget`, through the channel service. `accent="#rrggbb"` overrides the colour, and
    the text colour on it is chosen for contrast.
  - Answers stream in with progress ("Searching the documentation…", "Checking account-lookup…").
    The stored reply then replaces the streamed text and adds its verified citations.
  - Approvals show Yes/No buttons; a handoff confirmation shows "Send to the team" / "Not now".
  - "Talk to a person" asks for a handoff with a summary.
- **Rendering.** Everything is rendered as text, never HTML. Source links open only for
  `http(s)` URLs, with `rel="noopener noreferrer"`.
- **Languages.** English, Spanish and Arabic (right-to-left). Dark mode follows the system.

```bash
pnpm --filter @nexiqon/widget test
pnpm --filter @nexiqon/widget build   # dist/nexiqon-chat.js
```
