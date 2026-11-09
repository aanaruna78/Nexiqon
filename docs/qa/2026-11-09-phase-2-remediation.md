# Phase 2 remediation: response to the 9 November 2026 verification

Responds to [2026-11-09-phase-2-verification.md](2026-11-09-phase-2-verification.md). Branch
`phase-2/knowledge-ui`. Each finding was re-verified by running QA's reproduction files before any
change. All seven assertions failed as reported. QA's report, reproductions and evidence are
committed unchanged. Linters and whitespace hooks now skip `docs/qa/reproductions` as well as
`docs/qa/evidence`.

| Finding | Root cause (confirmed) | Fix | Regression tests |
|---|---|---|---|
| **QA2-01** (P1) restricted text sent to chat or rerank under a lower, caller-supplied label | Search hits did not carry their indexed classification; `answer()` and rerank passed `req.classification` | Hits, nodes and passages carry the **indexed** classification. Chat and rerank are labelled with the strictest of the request and every passage sent, so the model gateway routes (e.g. restricted to on-prem) or refuses on the true label. A refused rerank keeps the fused order. A refused answer abstains with reason `sensitivity` and calls no model | `test_qa2_01_*` (3): mixed sensitivities, a foreign embedding model reaching rerank via keyword search, refusal paths |
| **QA2-02** (P1) S3 connector re-resolved DNS after the check | `S3Client` used the hostname; the approved address was discarded | `S3Client(pinned_address=...)` connects to the checked IP and keeps the original Host header, TLS SNI and SigV4 signature. Used for listing and object fetches | `test_qa2_02_*` (2): request-level pinning; QA's scenario on real sockets (check approves 127.0.0.2, DNS rebinds to a 127.0.0.1 listener, the listener gets nothing). Both shown to **fail with pinning disabled** |
| **QA2-03** (P1) transient crawl failure deleted indexed documents | Failed fetches were skipped like absent pages; `finish_run` deleted anything unseen | Discovery is marked **incomplete** on any non-authoritative failure: network error, 5xx, 429, 401 or 403, robots.txt unavailable, sitemap unavailable. New column `runs.incomplete` (migration `ingestion/0002`). Incomplete or truncated runs never delete. Only a page that is gone (404/410) or no longer linked proves removal. Studio explains incomplete runs | `test_qa2_03_*`: 503, 429, 403 and robots 500 keep both documents (`incomplete=true`, `deleted=0`); a later 404 deletes |
| **QA2-04** (P2) outline disclosed hidden titles and headings | Outline and stats queries skipped search's visibility filter | Outline and stats apply the same predicates as search (`adapters/pgvector.visibility`): hidden is 404 and zero counts. **Same gap found in ingestion** (collections, documents, sources, runs listed to members outside a collection's groups): closed with one rule, hidden collections return 404 | Outline/stats in `test_index.py`; `test_qa2_04_*` covers every ingestion read route for outsider, insider and editor |
| **QA2-05** (P2) one supported marker validated an unsupported occurrence | Support tracked per marker, not per sentence | Each sentence is judged alone. Unsupported sentences lose their markers and are reported as removed | `test_qa2_05_each_occurrence_is_checked_on_its_own` |
| **QA2-06** (P2) first passage exceeded `max_context_tokens` | The oversized first group bypassed the budget | An oversized first match is cut at a word boundary to fit (ellipsis included in the count) and flagged `truncated`. Later groups that do not fit are skipped. Studio marks shortened passages | `test_qa2_06_context_cap_holds_for_the_first_passage` (caps 256 and 300) |

**Policy decision made while fixing QA2-04.** Owners, admins **and editors** see every collection
regardless of access groups (`acl_bypass_roles` in retrieval, `content_manager_roles` in ingestion; the
two must match). Editors manage knowledge, so hiding content from them would make Studio unusable.
Members, end users and widgets are bound by groups, and widgets also by the classification ceiling.
Change the settings if you want a stricter rule.

## QA's reproduction files after the fixes

| File | Result |
|---|---|
| `phase2_retrieval_cases.py` | **5 passed** |
| `phase2_ingestion_cases.py` | **1 passed, 1 error**: the transient-crawl case passes. In the S3 case the pinned client now connects to the *approved* address `93.184.216.34`, which does not answer on the test's ephemeral port, so the call times out (`ConnectTimeout`) before the script's `assert not hits`. The loopback listener received **no** request. The intended property holds; the socket-level regression `test_qa2_02_dns_rebinding_cannot_redirect_a_real_socket` asserts it directly and fast. |

## Re-run after fixes

| Check | Result |
|---|---|
| Lint, format, strict mypy (201 files), architecture | Pass |
| Contracts and generated TS client | Regenerated: `classification`/`truncated` on passages, `incomplete` on runs |
| `pytest` | **339 passed** (330 + 9 regressions) |
| OPA | **14 passed** |
| Studio typecheck, lint, unit tests | Pass, **23** tests |
| Stack rebuilt from this checkout (migration 0002 applied); browser suite with axe, EN and AR | **17 passed** |
| Gateway smoke | **26 checks passed** |

Unchanged and still open, as QA listed: live provider interoperability, M-07 with real models,
production-scale concurrency and budget races, external S3 and Git behaviour, a live Grafana alert firing,
and browser E2E in CI.
