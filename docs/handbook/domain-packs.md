# Domain Packs

A Domain Pack describes one field: a clinic front desk, a SaaS help centre, an IT service desk. It
holds everything an assistant needs that is specific to that field, so the platform itself stays
domain-agnostic. Assistants are built on a pack and can override some of its settings.

You can edit a pack in Studio (**Domain Packs**), or keep it as YAML in Git and import it. Studio's
**YAML** tab exports the last saved version.

## Structure

```yaml
apiVersion: nexiqon.dev/v1
kind: DomainPack
metadata:
  name: saas-knowledge-assistant      # lowercase letters, digits and dashes
  title: SaaS Knowledge Assistant
  version: 1.0.0
  locales: [en]                       # every text below has one entry per locale
spec:
  vocabulary: { ... }                 # the words your users and staff use
  intents: [ ... ]                    # what people ask for, and who handles it
  graph: { ... }                      # the workflow the assistant follows
  prompts: { ... }                    # instructions for each step
  sources: [ ... ]                    # recommended connectors
  tools: [ ... ]                      # tools the pack expects, with their risk
  guardrails: { ... }                 # topics, evidence, redaction, citations
  escalation: { ... }                 # when to hand over to a person
  channels: { widget: { ... } }       # widget title, greeting, starter questions, colour
  evals: { ... }                      # test questions and quality thresholds
  analytics: { kpis: [ ... ] }        # the KPIs shown in Insights
  agent_defaults: { ... }             # defaults for assistants built on this pack
```

## Vocabulary

These are the words Studio and the assistant use, one label per locale:

```yaml
vocabulary:
  case: { en: Support ticket, fr: Ticket d'assistance }
  customer: { en: Customer }
```

## Intents

An intent is something people ask for. Its **route** decides who handles it:

| Route | Meaning |
|---|---|
| `knowledge` | Answer from the knowledge collections, with citations |
| `action` | Use a tool (listed in `tools`) |
| `handoff` | Hand over to a person |
| `smalltalk` | Greetings and thanks; no search |

A few example phrasings per intent route most questions without a model call. That is faster and
cheaper, and the Answer Inspector shows that the examples decided the route.

```yaml
intents:
  - name: product_question
    route: knowledge
    examples: ["How do I invite a teammate?", "Why is my webhook failing with a 401?"]
  - name: account_lookup
    route: action
    tools: [account-lookup]
    examples: ["What plan am I on?"]
```

## Workflow

The graph lists the steps (nodes) and the conditions that move between them (edges). The node
types are:

- `route`: understand the question;
- `retrieve`: search the knowledge;
- `call_tool`: use a tool;
- `approve`: ask the user to confirm a change;
- `validate_evidence`: check that the sources support an answer;
- `clarify`: ask one question back;
- `respond`: answer;
- `escalate`: hand over to a person.

Studio checks the graph before saving and draws it on the **Workflow** tab.

## Prompts

Each step's instructions may use only the variables listed for it, such as `{{assistant_name}}`,
`{{product_name}}`, `{{tone}}` or `{{question}}`. Never put secrets in prompts: tools get their
credentials from the secret store. The platform always treats source text as data, never as
instructions, whatever the prompt says.

## Guardrails and handover

```yaml
guardrails:
  blocked_topics: [legal advice]      # a fixed refusal; no model sees the question
  min_evidence_score: 0.6             # below this, the assistant does not answer from the sources
  pii_redaction: true                 # hide personal data from cloud models
  cite_sources: true
escalation:
  on_low_evidence: true
  on_user_request: true
  after_failed_turns: 2
  handoff_tool: create-ticket         # the user confirms the summary before it is sent
```

## Tools

A pack names the tools it expects and their risk:

```yaml
tools:
  - { name: account-lookup, risk_level: read, confirmation: never }
  - { name: create-ticket, risk_level: write, confirmation: always }
```

The tools themselves are connected in **Actions & integrations**, usually by importing an OpenAPI
description. The effective risk is always the stricter of the pack's setting and the tool's own,
and writes always ask the user first.

## Evaluations and KPIs

`evals.test_sets` ship test questions with the pack. When you create a test set **from a pack**,
these become its cases. `analytics.kpis` defines the domain KPIs that Insights shows, such as the
deflection rate.

## Versions and release

Saving creates a **draft**. Releasing publishes an immutable **version** and deploys it to an
environment.

- Assistants pick up the pack version they were released with.
- Each release shows what changed since the previous version, and you can roll back from
  **Versions**.
- Packs can be imported and exported as YAML (**Import YAML** and the **YAML** tab), so they can
  live in Git and go through code review.
