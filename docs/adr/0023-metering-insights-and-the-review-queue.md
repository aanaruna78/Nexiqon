# ADR 0023: Metering, insights and the review queue

Status: Accepted (2026-11-19)

## Context

Phase 4 needs:
- **Cost:** what the platform costs per assistant, matching what the model gateway recorded, with
  budgets and alerts (MT-01, UX G8).
- **Quality:** how well assistants answer and what they cannot answer yet (MT-02, UX G3).
- **People:** a place where people pick up conversations the assistant handed over (ST-16).

## Decision

- **Metering is a read model built from events.**
  - It subscribes to `nexiqon.>` and keeps three daily views: usage (by assistant, operation,
    profile, provider and model), activity counters, and per-conversation facts.
  - Every event id is recorded in the same transaction as its counters, so redelivery never counts
    twice.
  - The tables can be rebuilt by replaying events. The sources of truth stay where they were:
    model-gateway's usage records, conversation's messages, and tool-gateway's call log.
- **Usage is attributed to assistants at the source.**
  - Agent-runtime sends `agent` with every model call; model-gateway stores it and includes it in
    `usage.recorded`.
  - Calls without an assistant (indexing, previews) are counted under "no assistant".
  - A test drives the real gateway and replays its outbox into metering. Calls, tokens and cost
    equal the gateway's own `/v1/usage` report (MT-01 acceptance).
- **Budgets alert, they do not block.**
  - Monthly budgets are set for the organization or one assistant, with thresholds (default 50%,
    80% and 100%).
  - Each threshold raises at most one alert per month, plus a
    `metering.budget.threshold_reached` event that notifications can deliver.
  - Hard limits remain the per-profile `budgets.monthly_usd` that model-gateway already enforces
    on every call. Metering's view is a few seconds behind and must not be a gate.
  - Only admins change budgets; editors and members can see spend.
- **Quality and KPIs.**
  - Quality rates come from the counters: answered, with sources, handed to a person, rated
    helpful, action errors. Each is compared with the previous period.
  - A pack's `analytics.kpis` names an event, and the KPI is the share of conversations in which
    that event happened. `conversation.resolved` is derived: answered and never handed over.
  - Conversation now emits `conversation.started`. Feedback events carry the assistant and the
    conversation.
- **Content gaps.**
  - Conversation lists the questions that went wrong (`GET /v1/insights/gap-questions`):
    - the assistant abstained;
    - it had to ask the person to rephrase for lack of evidence;
    - it handed over;
    - its answer was rated unhelpful.
  - Metering fetches these as its own identity (`service:metering`, ADR 0017) and groups them by
    topic with TF-IDF and greedy cosine clustering. This is deterministic and model-free, and it
    works for any script.
  - The report contains visitors' own words, so it needs `metering.gaps.view` (editors and admins),
    not a plain read.
  - "Answer this" opens the fix loop (ADR 0021) on the topic's most typical question.
- **Review queue.**
  - A handover puts the conversation in the queue (`open`). Staff can claim it, give it back,
    resolve it, or reopen it (`conversation.queue.write`; widget keys never can).
  - Staff can reply in a handed-over conversation (`role: "staff"`); the assistant stays quiet
    there.
  - The widget checks for team replies every 8 seconds while the conversation is with a person.
    Pushing them to the browser can come with notifications (NT-01).
  - Studio's reader moves through conversations with j/k, and opens "Why this answer" and "Fix
    this answer" from any reply.

## Consequences

- Studio's Conversations and Insights sections are live; no section is "coming soon" any more.
- Metering, conversation and evaluation each have their own signing key, mounted only in their
  own deployment group.
- Retention of metering's processed-event ids, and webhook delivery of alerts, are governance and
  notification work (G-01, NT-01).
