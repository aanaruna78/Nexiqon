# Accessibility audit (UX-10), 2026-11-20

**Result: zero findings, at any impact level, on every Studio page, in four languages and both
themes.** The UX-10 bar was zero critical findings.

## Scope and method

- **Automated scan.** axe-core 4.14, through `@axe-core/playwright` 4.14, against WCAG 2.0, 2.1
  and 2.2 A and AA (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`). The tool lives in
  `frontend/apps/studio/e2e/a11y-audit.spec.ts`.
- **Environment.** A signed-in owner, against the full local stack, in an organization with
  content (assistants, packs, test sets, conversations), with reduced motion on.
- **Pages:**
    - every route: Home, Get started, Assistants, Knowledge, Playground, Conversations, Insights,
      Evaluations, Domain Packs, Actions, and Settings (overview, members, API keys, audit log,
      configuration, models and data policy, organization, webhooks);
    - the first detail page of assistants, Domain Packs and test sets.
- **Variants:** English (light and dark), French, Spanish, and Arabic (right-to-left; light and
  dark).

| Run | Pages scanned | Findings |
|---|---|---|
| English, light | 21 | 0 |
| English, dark | 21 | 0 |
| French, light | 21 | 0 |
| Spanish, light | 21 | 0 |
| Arabic (RTL), light | 21 | 0 |
| Arabic (RTL), dark | 21 | 0 |
| **Total** | **126** | **0** |

The Arabic dark run was repeated once: the first attempt stopped on a host network suspension
(`ERR_NETWORK_IO_SUSPENDED`), not on a finding.

**The knowledge collection page** is not in this table: the audit's organization had no
collection left. That page is scanned in the main end-to-end flow (`e2e/studio.spec.ts`), which
fails on serious or critical findings on every screen it opens.

## Also checked (tests and code)

- **Keyboard:**
    - the command palette opens with Ctrl+K and navigates by keyboard;
    - the help dialog lists the shortcuts;
    - the conversation queue moves with j and k (`aria-keyshortcuts`).
- **Right-to-left:** switching to Arabic mirrors the whole interface (`dir="rtl"`) and translates
  every message.
- **Reduced motion:** every scan ran with `prefers-reduced-motion: reduce`.
- **Colour:**
    - the brand primary meets WCAG AA contrast with white text;
    - organization accent colours are adjusted until they do (`test/theme-i18n.test.ts`);
    - the widget does the same for pack colours.
- **The website widget** has its own checks (`docs/guides/widget-accessibility.md`). For example,
  each finished answer is announced once, not every streamed word (a widget unit test).

## Languages added (UX-10)

French and Spanish join English and Arabic: 1,271 messages each.

**A test checks every language against English:**

- the same keys;
- the same ICU arguments, including those inside plural branches;
- every message formats without leftover syntax.

It caught a deliberately broken placeholder during development. The organization's default
language and the language menu list all four languages.

## Not covered

- **Assistive-technology sessions.** No one has yet done a full pass with screen readers (NVDA,
  VoiceOver, TalkBack). axe finds roughly half of WCAG issues; a manual screen-reader pass by an
  accessibility specialist is recommended before launch (Phase 5).
- **No professional linguist has reviewed the translations yet** (French and Spanish, and also
  Arabic). Native speakers should review them before customer launch in those languages.
