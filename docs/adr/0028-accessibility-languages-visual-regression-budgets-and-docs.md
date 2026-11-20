# ADR 0028: Accessibility audit, more languages, visual regression, budgets and the docs site

Status: Accepted (2026-11-20)

## Context

Phase 4 slice 9 finishes the phase with four backlog items:

- **UX-10:** an accessibility audit with zero critical findings, and two more UI languages;
- **UX-11:** visual regression and performance budgets enforced in CI;
- **D-01:** a public documentation site.

## Decision

- **Accessibility audit** (`e2e/a11y-audit.spec.ts`):
  - axe (WCAG 2.2 AA) scans every Studio page and the main detail pages, in English, French,
    Spanish and Arabic, light and dark.
  - Serious and critical findings fail the run, and every finding is recorded.
  - Result: 126 scans and **zero findings at any impact level**
    (`docs/qa/2026-11-20-accessibility-audit.md`).
- **French and Spanish** join English and Arabic: 1,271 messages each.
  - A test checks every language against English: the same keys, the same ICU arguments (also
    inside plural branches), and every message formatting cleanly.
  - The test was shown to catch a broken placeholder.
- **Visual regression** (`frontend/apps/studio/visual`):
  - Every Storybook story is screenshotted in four variants (light/dark × LTR/RTL), and so is the
    website widget in its key states (launcher, greeting, an answer with sources, a confirmation)
    in light, dark and Arabic, against a mocked gateway.
  - Screenshots are compared with committed baselines.
  - Everything runs inside the pinned Playwright image (`mcr.microsoft.com/playwright:v1.64.1`),
    locally (`make visual`, `make visual-update`) and in CI, so the browser and fonts are
    identical everywhere. Diffs are uploaded when CI fails.
- **The suite found two real defects** while it was being built:
  - **Storybook rendered unstyled.** Its Vite build never ran Tailwind, so the design-system
    catalog, and the accessibility addon's checks on it, had been looking at unstyled pages.
    Fixed with `@tailwindcss/vite` 4.3.4 (the installed Tailwind version, released 2026-11-02).
  - **The widget showed template whitespace.** The answer bubble preserves line breaks
    (`pre-wrap`), so the template's indentation showed as an empty block before every answer and
    gaps around each source. Fixed, and covered by a unit test.
- **Performance budgets:**
  - `pnpm build` now fails when any Studio route's first-load JavaScript exceeds 350 KB gzipped
    (the largest is 314 KB), or when the CSS exceeds 28 KB (it is 23 KB). Measured from each
    route's client manifest.
  - The widget keeps its 60 KB budget (it is 18 KB).
  - Raising a budget is a deliberate change with a reason.
- **Docs site** (MkDocs Material 9.8.0, `mkdocs.yml`, `make docs`):
  - quickstart;
  - the Domain Pack guide;
  - the plugin SDK guide;
  - the API reference (generated from the OpenAPI contracts, with a test that keeps them equal);
  - install guides for SaaS, hybrid, private Kubernetes, one server and air-gapped (they include
    the deployment READMEs rather than copying them);
  - a security overview.

  Details:
  - Internal documents (plans, QA evidence, ADRs, runbooks, the threat model) are excluded.
  - The build is strict, so a broken link fails CI.
  - Publishing to GitHub Pages is a separate job, **off until `PUBLISH_DOCS=true`** is set:
    publishing is the owner's decision.
  - Writing the plugin guide showed that an entry point naming a plugin class (as the SDK's own
    docstring suggested) registers the class, not an instance. The docstring and the guide now
    point at an instance or a factory.

## Consequences

- A screen-reader pass by a person, and native-speaker review of the translations, are still to
  do; the audit says so.
- Visual baselines change only through `make visual-update`, and the PNG diff is part of the review.
- Material for MkDocs reaches end of life in May 2027. Its successor (Zensical) reads the same
  `mkdocs.yml`, so the move should be small; plan it before then.
