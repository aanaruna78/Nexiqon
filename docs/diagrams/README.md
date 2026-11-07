# Diagrams

Mermaid sources live in `src/*.mmd`. The rendered SVGs next to this file are what the docs in `docs/plan/` embed.
Edit the source, then re-render. Never edit the SVGs by hand.

```bash
cd docs/diagrams
PUPPETEER_SKIP_DOWNLOAD=1 npm install        # first time only; uses your installed Chrome
PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome npm run render              # all diagrams
PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome npm run render -- hybrid-mode  # just one
```

The shared theme (ThinkHive navy, teal and amber) is in `mermaid.config.json`. Labels are rendered as plain SVG
text (`htmlLabels: false`), so the images display correctly on GitHub, in VS Code and in other Markdown viewers.

| Diagram | Used in |
|---|---|
| system-overview, data-plane-services, request-sequence, events-outbox, deletion-saga, ports-adapters, ingestion-workflow, agent-graph, hierarchical-retrieval, config-hierarchy, domain-pack, config-lifecycle, deployment-modes, hybrid-mode, tenant-isolation | ARCHITECTURE.md |
| model-routing, roadmap-gantt, critical-path | PLAN.md |
| onboarding-journey, fix-loop, studio-ia | UX.md |
| deployment-groups | REVIEW.md |
