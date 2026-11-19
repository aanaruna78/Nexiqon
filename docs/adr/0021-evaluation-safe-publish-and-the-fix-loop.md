# ADR 0021: Evaluation, safe publish and the fix loop

Status: Accepted (2026-11-19)

## Context

Phase 4 needs a way to show that a new assistant version is at least as good as the live one
before it reaches users (QA-01, QA-02, UX G4). Content managers also need to repair a bad answer in
minutes, without editing YAML or waiting for a re-crawl (ST-14, UX G2).

## Decision

### Evaluation service (QA-01)

- **Test sets** are lists of cases. Each case has a question, a language, and optional
  expectations: the document and section to cite, phrases a right answer contains, or "the
  sources do not answer this".
  - Sets start from a pack's `eval/gold.yaml`, from cases written in Studio, or from bad answers
    saved through the fix loop.
  - Each set has a `revision` that every case change bumps.
- **Runs are Temporal workflows** (`evaluation.RunEvaluation`). Each case is its own activity and
  a fresh agent-runtime turn on a thread of its own. Cases run with bounded concurrency. A failing
  case is recorded as a failure and never stops the run.
- **Evaluation runs as itself** (`service:evaluation`, ADR 0017), with its own signing key
  (`evaluation_identity`).
  - Its role may ask assistants (including unreleased versions), search and read agent config.
  - It may **not** invoke tools, so an evaluation never changes anything.
  - Retrieval and ingestion treat it as a content manager (`acl_bypass_roles`). A score therefore
    reflects the assistant's full knowledge, not one person's view.
  - Because results hold answers made with that view, reading them needs
    `evaluation.results.view`. Reading expected answers needs `evaluation.cases.view`. Neither is a
    `read` permission, so members do not get them; editors and admins do.
- **Evaluators are plugins** (SDK `PluginKind.EVALUATOR`, entry-point group
  `nexiqon.evaluators`).
  - The built-ins are deterministic: source cited, contains facts, honest abstention, grounded.
  - A case passes when every evaluator that applies to it passes.
  - Model-graded evaluators can be added later as plugins that call the model gateway.
- **Scorecards** record:
  - pass rate and the mean of each evaluator;
  - pass rate by language;
  - p50/p95 latency, tokens and cost.

  `GET /v1/evaluations/reports` returns the latest scorecard per version.

### Safe publish (QA-02)

- An agent spec may declare `release_gate: {enabled, test_set, min_pass_rate, max_drop}`.
- When it is enabled, config's publish asks evaluation `POST /v1/gates/agents/{agent}/check`,
  using the **publisher's token**. It sends three things:
  - the version;
  - its `spec_hash`;
  - the version live in `gate_baseline_environment` (default dev), as the baseline.
- The gate passes when all of these hold:
  - a completed run exists for exactly this content: same version and same `spec_hash`, because
    drafts are edited in place;
  - the run used the test set's current revision;
  - it clears `min_pass_rate`;
  - neither the pass rate nor any evaluator falls more than `max_drop` below the live version's
    run on the same cases.
- A run also re-reads the hash when it finishes. If the draft changed mid-run, the run fails as
  `changed_during_run`.
- Failures are `409 release_gate_failed`, with reason codes that Studio translates. An evaluation
  service that is unreachable fails closed with `503`.
- **Override**: `override_reason` (at least 10 characters) requires `config.release.override`,
  which is admin-only in the policy. The gate answer and the reason are written to the
  `version.published` event, which is audited.

### Fix loop (ST-14)

- **Reviewed answers**: ingestion `POST /v1/collections/{id}/snippets` adds a Q&A snippet to the
  collection's snippet source, or replaces one for the same question. It creates the source if
  needed and syncs it straight away. Snippets already outrank other content (`snippet_boost`).
- **Outdated pages**:
  - ingestion `PATCH /v1/documents/{id} {outdated}` flags the index first, through retrieval's
    service-only `PATCH /v1/index/documents/{id}`;
  - search leaves flagged nodes out at once (outlines and stats still show them to managers);
  - indexing a new version clears the flag.
- **Keep it fixed**: the bad answer becomes a case in `<agent>-regressions`, linked to its run.
  The next gated release is checked against it.

## Consequences

- Release quality is enforced on the server, not only in Studio. Bypassing it takes an admin and
  leaves a record.
- Evaluation scores are made with the full view of the knowledge. Access-specific behaviour stays
  covered by the access preview (ST-08) and the policy tests.
- Tool-using flows are not exercised by evaluations yet: tools are refused. A safe tool sandbox
  for evaluations is future work.
