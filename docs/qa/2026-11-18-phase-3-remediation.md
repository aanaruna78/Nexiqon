# Phase 3 remediation, 18 November 2026

This responds to [2026-11-18-phase-3-verification](2026-11-18-phase-3-verification.md). All six
findings reproduced as reported (8 failing assertions across the four reproduction files) and
are now fixed. The QA report, its reproduction files and its evidence are unchanged byte for byte.

| ID | Fix | Regression tests |
|---|---|---|
| QA3-01 | Tool-call replays are looked up by tenant, tool, **assistant, caller** and key. The uniqueness constraint matches (tool-gateway migration 0002). The same caller retrying still gets the stored result; anyone else gets their own call. | `tool-gateway/tests/test_scopes.py::test_replays_belong_to_their_caller_and_assistant` |
| QA3-02 | The key's assistant scope (`agt` claim) applies at every entry point. Tool invoke, confirmations and `describe` require the assistant. Approval decisions and the approvals and calls logs are filtered by it. Dry runs, credentials, OpenAPI import and unscoped `describe` are refused for scoped keys. Conversation reads, lists, feedback and turns check the conversation's assistant (other assistants' conversations are "not found"). Run traces are filtered the same way. A broad role never widens a narrower key. | `tool-gateway/tests/test_scopes.py::test_keys_limited_to_assistants_stay_inside_them`, `conversation/tests/test_streaming.py::test_keys_limited_to_assistants_see_only_their_conversations`, `agent-runtime/tests/test_streaming.py::test_scoped_keys_read_only_their_assistants_runs` |
| QA3-03 | Confirmation follows the **effective** rules: the stricter risk of pack and definition, plus "always confirm" from either. It is enforced server-side on invoke. `GET /v1/tools/{name}?agent=` reports the effective risk and confirmation, and agent-runtime uses it, so the approval flow and the gateway agree. | `tool-gateway/tests/test_scopes.py::test_the_stricter_of_pack_and_definition_decides_confirmation` |
| QA3-04 | Each thread's checkpoint keeps `history_label`: the strictest classification of anything the assistant has said on it. It is kept by the runtime, never taken from the caller. Every call that includes history (small talk, grounded answers, argument extraction, handover summaries) is labelled at least that strictly, so restricted content stays on the profiles allowed to see it. Answers record their `classification` in the stored contract. | `agent-runtime/tests/test_streaming.py::test_history_keeps_the_label_of_what_was_said`, `conversation/tests/test_streaming.py::test_restricted_answers_keep_later_calls_restricted` |
| QA3-05 | Streamed text passes a `StreamGuard` before it leaves. The last 8 words (the length of the system-prompt run that stops the stream, so none of such a run is ever released) and anything inside an unfinished link, image or tag are held back. Released text has already been through the output guard. Streaming stops at the first 8-word run of the system prompt, so nothing held back is ever sent. The final checked answer still replaces the stream. | `agent-runtime/tests/test_streaming.py::test_stream_never_releases_a_withheld_system_prompt`, `::test_stream_guard_holds_back_unsafe_text` |
| QA3-06 | Retrieval computes hidden-source counts only for knowledge managers, or when the request carries a **verified agent-runtime service token** for the same tenant (`x-nexiqon-diagnostics`; Envoy strips it from outside requests). agent-runtime sends that proof and redacts the count from every non-staff response: immediate run results, stream results and traces. | `retrieval/tests/test_search.py::test_hidden_counts_are_staff_diagnostics`, `agent-runtime/tests/test_streaming.py::test_hidden_counts_reach_staff_only_in_every_response` |

Also fixed: the extra blank lines at the end of four files noted in the report.

## Verification

- QA reproductions, run exactly as the report gives them: tool **3 passed**, conversation
  **2 passed**, agent **2 passed**, retrieval **1 passed**.
- Full Python suite: **444 passed** (435 before, plus 9 regression tests). Lint, strict mypy
  (238 files), architecture (0 violations), contracts and OPA (**20/20**) are clean.
- Frontend: lint, types, **49 unit tests**.
- Live stack, rebuilt; tool-gateway migration 0002 applied by `migrate`. Through the gateway:
  - QA3-01: the same caller replays; a different caller is not a replay and gets their own
    account.
  - QA3-02: a key limited to another assistant gets 403 on the tool, and its conversation list
    is empty.
  - QA3-03: `create-ticket` defined as read/never is reported as write/confirm and refused
    without confirmation.
  - QA3-05: a widget stream delivers the complete checked answer progressively.
  - QA3-06: the staff trace carries the count; a widget gets none, even with a forged
    `x-nexiqon-diagnostics` header.
  - Gap checks (snippets, download links, scoped keys, draft runs) still pass.
- Studio browser suite: **23 passed** with EN/AR axe scans.
- `git diff --check` is clean.

Not covered, as the report notes: real-model and GPU behaviour, live third-party APIs and
production load. Phase 3 acceptance still needs the gap fixes committed and green CI on that
commit.

## Independent QA re-verification — 18 November 2026

**QA3-01 through QA3-06 are closed for the reported reproduction cases.** Reviewed the current
uncommitted `phase-3/gaps` working tree on HEAD `dbf70734281e835decccbc998fc5bd379c5fe8a5`.
All eight original acceptance checks pass, and no additional blocker was observed in this review.
This closes the six code findings; committing the result and obtaining green CI remain release gates.

| Independently checked | Result |
|---|---|
| Original QA reproduction files, unchanged | Tool **3 passed**, conversation **2 passed**, agent **2 passed**, retrieval **1 passed** |
| Full Python suite, including the new maintained regressions | **444 passed**, no skips, 2 deprecation warnings, **192.14 seconds** |
| Python lint/format, strict mypy, architecture, OpenAPI freshness | Pass; **238** source files type checked, zero architecture violations |
| Generated TypeScript contracts | Byte-for-byte match when generated into a temporary directory; existing uncommitted generated files left untouched |
| Frontend lint, types, unit tests and fresh production builds | Pass; **38 Studio + 11 widget = 49 unit tests** |
| Rebuilt Studio browser suite against the running stack | **23 passed**, including EN/AR axe scans, **48.6 seconds** |
| OPA policy tests | **20 passed** |
| Real gateway smoke | **26 checks passed** |
| Running development Postgres, read-only inspection | Tool-gateway migration **0002**; uniqueness is **`(tenant_id, tool, agent, actor_id, idempotency_key)`** |
| `git diff --check` | Clean |

Source review confirms replay ownership/uniqueness alignment; assistant scope checks on tool,
approval, conversation and run-read paths; effective confirmation rules; checkpoint-held history
classification; streaming guards; and diagnostic authorization/redaction. The complete SSE
reproduction now withholds the system prompt before delivery, not only in the final answer.

GitHub's API still returns **no workflow runs for `phase-3/gaps`**. Earlier green slice runs do not
cover these uncommitted changes. No fresh backend image build or independent security scan was
performed in this re-verification. The browser/gateway checks used the existing backend stack;
the full Python and reproduction suites exercised the reviewed local sources through their fixtures.
The exclusions in the original report remain open.

Outputs and the starting file-hash manifest are preserved in
[evidence/2026-11-18-phase-3-remediation](evidence/2026-11-18-phase-3-remediation/).
All 97 pre-existing modified/untracked files matched their recorded hashes before this note was
appended. Only this QA note and new evidence were added; application code and the original QA
reproductions were left untouched. The QA-owned Studio server was stopped after the browser run.
No commit, merge, push or stack rebuild was performed.
