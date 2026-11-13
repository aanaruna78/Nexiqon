# @nexiqon/studio

The admin app for building and running assistants (Next.js, React Query, next-intl in English and
Arabic). The browser talks only to Studio's backend-for-frontend (`/api/nx/...`), which attaches
the signed-in user's token. Tokens never reach the browser (ADR 0016).

| Section | What it does |
|---|---|
| **Assistants** (ST-06) | Create an assistant from a Domain Pack. Tabs: **Setup** (identity, knowledge, models, tool allowlist, guardrails and handover), **Test** (streamed chat against the version live in dev), **Access preview**, **Versions** (readable diff against what is live, release, one-click rollback, release history) and **Workflow**. |
| **Answer Inspector** (ST-07) | From any test reply: a plain-language "why", sources with relevance scores (cited ones marked), tool calls, model, tokens, cost, time per step, and the path through the workflow. |
| **Access preview** (ST-08) | Exactly what a person in chosen access groups, or a website visitor, can retrieve, and how many passages you can see are hidden from them (a count only). Available to people who manage knowledge, since it can only narrow what they already see. |
| **Actions** (ST-09) | Tools with risk badges, allowed hosts, credential status and which assistants use them. Also: a dry-run console that shows the exact request without sending it, OpenAPI import, write-only credentials, and the approvals and call logs. |
| **Domain Packs** (ST-10) | Create a pack from a template, copy one or import YAML. Edit vocabulary, intents and examples, prompts, guardrails, handover, and widget copy (with a live preview). Validate the workflow, export YAML, and release with a diff. |
| **Workflow viewer** (ST-11) | A read-only picture of the declarative graph. In the Inspector it highlights the path a run took. |
| **Models & data policy** (ST-12) | Each model profile in plain terms (data location, quality, cost, personal data and training), which assistants use it, and where data of each classification goes. |

Also: Knowledge, Playground, Members, API keys, Configuration, Audit and Organization.

```bash
pnpm dev            # http://localhost:3100, against the dev gateway
pnpm test           # unit and component tests (Vitest, axe)
pnpm e2e            # end to end against the full stack, see e2e/README.md
```
