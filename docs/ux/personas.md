# Personas (draft, to validate in interviews)

## P1 · Priya, Knowledge Manager / Support Lead (primary)
- **Context:** SaaS company, 20–200 people. Owns help-centre content and support quality. Not a developer.
- **Goal:** an accurate assistant on the product docs that deflects repetitive questions and hands off cleanly.
- **Fears:** confident wrong answers, embarrassing the brand, spending days on setup.
- **Success looks like:** live in an afternoon; sees why an answer was wrong and fixes it in minutes; weekly gap report shows which docs to write.
- **Design implications:** plain language, Answer Inspector, one-click fix loop, onboarding wizard, Insights.

## P2 · Daniel, Tenant Admin / IT
- **Context:** owns identity, security reviews, vendor risk.
- **Goal:** control who can see what, where data goes, what it costs.
- **Fears:** data leaking to a model provider or another customer; audit gaps.
- **Design implications:** roles, audit log, model and data policy in plain language, retention settings, cost budgets.

## P3 · Mei, Developer / Integrator
- **Context:** backend engineer asked to "connect the assistant to our account API".
- **Goal:** add an account-lookup tool and embed the widget without reading a manual.
- **Fears:** unclear errors, unsafe write actions, auth plumbing.
- **Design implications:** OpenAPI import, dry-run console, clear error messages, copy-paste embed snippet.

## P4 · Sam, End user (the customer's customer)
- **Goal:** a fast, correct answer, or a human, in their own language.
- **Design implications:** cited answers, honest uncertainty, one-tap handoff with context, accessible widget, RTL.

## P5 · Operator (ThinkHive)
- **Goal:** keep many tenants and deployments healthy.
- **Design implications:** tenant health, usage, incidents at a glance (P2 scope).
