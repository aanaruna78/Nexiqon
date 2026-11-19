# Widget accessibility walkthrough (W-02)

The widget targets WCAG 2.2 AA.

- **Automated:** Studio's end-to-end suite loads the live widget on a test page and runs axe in
  light, dark and Arabic (right-to-left). It also checks keyboard focus and answer announcements.
- **Manual:** run this walkthrough before each release with at least one screen reader. Use NVDA
  with Firefox or Chrome on Windows, or VoiceOver with Safari on macOS or iOS.

Record the date, the screen reader and its version, the browser, the widget version, and any
finding with its WCAG criterion.

## Setup

Embed the widget on a plain page (see `frontend/apps/widget/README.md`) with an assistant whose
documents answer "How long is each backup kept?". Test with `locale="en"` first, then
`locale="ar"`.

## Steps and what you should hear or see

1. **Find it.** Tab through the page. The last stop is a button named "Ask a question", or the
   pack's title, announced as collapsed.
   *Expected:* the button is reachable by keyboard, has a visible focus ring, and is announced as
   collapsed (2.1.1, 2.4.7, 4.1.2).
2. **Open it.** Press Enter. The dialog opens with its title, and focus moves to the question box.
   *Expected:* "dialog, Help"; "Type your question, edit text" (2.4.3, 4.1.2).
3. **Starter questions.** Shift+Tab back to the starter buttons. Each one reads as a button with
   its full question (2.4.6).
4. **Ask.** Type the question and press Enter. While the answer streams you hear "Searching the
   documentation…" and "Writing…", but not every word.
   *Expected:* once the answer is complete, it is announced once: "Help answered: … 35 days …"
   (4.1.3).
5. **Sources.** Arrow into the answer. The "Sources" list is announced with its item count. Links
   say where they go and open in a new tab (1.3.1, 2.4.4).
6. **Rate it.** Tab to "Helpful" and press Space. It is announced as a toggle button, pressed.
   Then choose "Not helpful": a labelled box "What was missing? (optional)" appears, and "Send
   feedback" confirms (4.1.2, 3.3.2).
7. **Suggestions.** "You could also ask" is followed by up to three question buttons.
8. **Not sure.** Ask something the documents don't cover.
   *Expected:* the answer starts with "Not sure", and an "Ask a person instead" button follows it
   (3.3.1).
9. **Confirm an action.** If the assistant has a write tool, ask it to do something.
   *Expected:* a group named "Please confirm" says "Nothing happens until you choose", with "Yes,
   go ahead" and "No, thanks". The question box is disabled until you choose (3.3.4).
10. **Email a copy.** Activate "Email me a copy", fill in "Your email address" and send.
    *Expected:* the status "Sent. Check your inbox." is announced without moving focus (4.1.3).
11. **Close.** Press Esc. The dialog closes and focus returns to the launcher, now announced as
    collapsed (2.4.3).
12. **Zoom and reflow.** Zoom to 400% or set a 320 px wide viewport. Nothing is cut off and there
    is no horizontal scrolling inside the widget (1.4.10). Increase text spacing (1.4.12) and check
    again.
13. **Colours.** Repeat steps 2–7 with `theme="dark"`, and with the system in dark mode and
    `theme="auto"`. Text and focus rings stay readable. The accent colour is darkened
    automatically if white text on it would fall below 4.5:1 (1.4.3, 1.4.11).
14. **Arabic.** Repeat steps 1–6 with `locale="ar"`.
    *Expected:* the layout is right-to-left; questions and answers are read in Arabic; controls
    keep their Arabic names.
15. **Reduced motion.** With "reduce motion" on, the dialog appears without animation (2.3.3).

## Known limits

- The widget does not trap focus. It is a non-modal dialog, so the page stays usable behind it.
  Esc and the close button both return to the launcher.
- Answers are plain text. A pack that needs headings or tables inside answers should keep them
  short; the widget does not render rich text.
