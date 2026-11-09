# Phase 2 verification — 9 November 2026

**Verdict: testing completed; acceptance withheld.** The existing suites and all four branch CI runs pass, but seven additional acceptance checks reproduce **six findings**, including three high-priority data handling/security failures. No application code was changed.

## Scope

Reviewed `phase-2/knowledge-ui` at **`4e7bf06a4e1f01b8b9ad43f01823ab200983ac5f`**, initially clean. Confirmed local branch ancestry:

`phase-1/qa-fixes` → `phase-2/model-gateway` → `phase-2/ingestion` → `phase-2/retrieval` → `phase-2/knowledge-ui`.

Tests covered model routing, budgets and usage through the existing gateway tests; plugin discovery, parsing, ingestion workflows and index writes; hybrid retrieval, filters, citations and the offline quality gate; and Studio Knowledge/Playground flows. Additional probes targeted sensitivity propagation, metadata access, incomplete crawls, DNS rebinding, repeated citation markers and context limits.

The local stack and Studio were already running. Gateway/browser/live-scanner checks used those running services. A separate image was built from the reviewed source and smoke-tested in a new temporary container; the full development stack was not replaced or independently rebuilt. External model-provider adapters were exercised with test doubles, not paid/live provider calls.

## Results

| Check | Observed result |
| --- | --- |
| Frozen Python and pnpm dependency installs | Pass |
| Python lint and formatting | Pass; 328 files at baseline |
| Strict mypy | Pass; 200 source files |
| Architecture rules | Pass; zero violations |
| OpenAPI freshness and generated TypeScript client diff | Pass; generated types unchanged |
| Full Python suite | **330 passed**, no skips, 3 deprecation warnings, 85.16 seconds |
| Frontend lint, types, unit tests and production builds | Pass; **23 Studio + 3 widget tests** |
| OPA policy tests, Docker image 0.70.0 | **14 passed** |
| Existing gateway smoke | **26 checks passed**; this script primarily exercises the foundation, not the whole Phase 2 pipeline |
| Browser suite against running stack | **17 passed**, including Knowledge, Playground and EN/AR axe scans, 24.7 seconds |
| Offline retrieval quality gate | Pass; **29 questions**, Recall@5 **1.0**, evidence **1.0**, P95 **29.28 ms** with expansion |
| Flat retrieval baseline | Recall@5 **1.0**, evidence **0.931**, P95 **12.41 ms** |
| Real ClamAV/Temporal ingestion through the gateway | Clean restricted document became `ready`; EICAR test file became `quarantined` with `malware_detected`, scanner `clamav`; quarantined outline returned **404** |
| Source image build using local legacy Docker builder | Pass; tag `nexiqon/platform:phase2-qa` |
| New container from that image | `/healthz` and `/identity/meta` returned **200**, UID **10001**; container removed afterward |
| Additional acceptance cases | **7 failed assertions across 6 findings**, below; no fixture/setup errors in the final reproduction runs |

The quality set contains 23 English, 3 Spanish and 3 Arabic questions. Its deterministic hash embeddings test retrieval machinery; these scores do not establish real-model answer quality. Browser axe checks reject serious/critical violations on the visited screens and do not certify full accessibility or mobile usability. The live EICAR check confirms the scanner/quarantine/index outcome; it does not directly instrument parser execution.

## Findings

| ID | Priority | Finding |
| --- | --- | --- |
| QA2-01 | **P1** | Restricted passages are sent to chat/reranking under a caller-supplied lower classification |
| QA2-02 | **P1** | S3 connector checks DNS but does not pin its subsequent connection; DNS rebinding reaches loopback |
| QA2-03 | **P1** | Temporary crawler HTTP failures cause deletion of previously indexed documents |
| QA2-04 | **P2** | Outline endpoint exposes titles/headings of documents hidden by access groups |
| QA2-05 | **P2** | A supported citation occurrence validates unsupported occurrences of the same marker |
| QA2-06 | **P2** | Section expansion exceeds a valid configured context-token cap |

### QA2-01 — Preserve source sensitivity across every model boundary

Sources: [retrieval API](../../services/retrieval/src/nexiqon_retrieval/api.py#L519), [answer generation](../../services/retrieval/src/nexiqon_retrieval/answer.py#L70), [reranking](../../services/retrieval/src/nexiqon_retrieval/search.py#L212).

Two reproductions capture the model-client boundary:

1. Index a synthetic **restricted** payroll passage. Submit `POST /v1/answer` as an authorized tenant member with `model_profile=cloud-frontier`, `classification=internal`, and the existing `dev-offline` retrieval profile. The endpoint returns **200** and sends the restricted source text to chat with **classification `internal`** and the cloud-selected profile.
2. Index a restricted document using a different embedding-model identifier (`onprem-only-model`). Submit `POST /v1/search` with the cloud profile, `classification=internal`, and `rerank=true`. Keyword retrieval still selects the document and the reranking client receives its text under **classification `internal`**, despite the different vector space.

Both tests use synthetic text and an instrumented offline client; no confidential data was sent to an external cloud. They prove that retrieval passes the wrong label at the downstream boundary. The model gateway's restricted-data guard cannot enforce a restriction it is not told about. This is separate from whether the caller may read the passage.

**Expected:** derive downstream sensitivity from trusted indexed/source metadata, at least as strict as every included passage; route or refuse before sending source text to reranking/chat. Do not rely solely on the request body's classification. Carry classification through hit/passage results and test mixed sensitivities and embedding models.

### QA2-02 — Pin S3 connections to the checked address

Sources: [S3 connector client construction](../../services/ingestion/src/nexiqon_ingestion/plugins/connectors.py#L236), [S3 HTTP request](../../libs/nexiqon-core/src/nexiqon_core/adapters/s3.py#L99).

The connector calls `ctx.check_host(endpoint)` but discards the approved address and constructs a normal S3 HTTP client using the original hostname. That client performs another DNS resolution.

The reproduction starts a local HTTP listener, makes the safety resolver approve **93.184.216.34**, then makes the connection resolver return **127.0.0.1** for the same synthetic hostname. The listener receives:

```text
GET /docs?list-type=2&prefix= HTTP/1.1
```

No private CIDR was allowed. An ephemeral port was explicitly allowed in the test policy; the defect is the unchecked address, not the port. The test uses dummy S3 credentials and only a loopback server.

**Expected:** the S3 transport must connect to the validated address while preserving the original Host/SNI/signing identity, or perform equivalent connection-level validation. Apply the same guarantee to listing and object fetches. The general `SafeFetcher` already pins connections; this connector bypasses that transport.

### QA2-03 — An incomplete discovery must not become evidence of deletion

Sources: [crawler warnings and skipped pages](../../services/ingestion/src/nexiqon_ingestion/plugins/connectors.py#L161), [discovery completion metadata](../../services/ingestion/src/nexiqon_ingestion/pipeline.py#L183), [stale-document deletion](../../services/ingestion/src/nexiqon_ingestion/pipeline.py#L503).

In the real Postgres/Temporal fixture:

1. Sync a synthetic site with `/` linking to `/a`; both documents index successfully.
2. Keep that link but make `/a` return **503** on the next sync.
3. The run reports **`completed`**, warning **`HTTP 503`**, **`deleted=1`**. Only `/` remains in the document listing.

The crawler treats a transient fetch failure as a skipped discovery result. `finish_run` then interprets the missing URI as a removed source document and deletes its index/file through `delete_document`.

**Expected:** mark discovery incomplete on transient fetch/sitemap/robots failures and preserve prior documents; retry or report a partial/failed run. Delete only when a complete, authoritative discovery establishes removal. Keep genuinely removed-source deletion coverage as well.

### QA2-04 — Apply access filters to outline metadata

Source: [outline endpoint](../../services/retrieval/src/nexiqon_retrieval/api.py#L232).

Index a restricted document with access group `legal`. A `member` in group `engineering` gets **no search passages**, as expected. The same member's direct outline request returns **200**, including the synthetic title **“Secret acquisition”** and heading **“Confidential deal price”**.

The endpoint checks the broad `retrieval.index.read` action and tenant RLS, but its SQL does not use the access-group/classification filters applied by search.

**Expected:** return 403/404 or only authorized metadata. This is a same-tenant information disclosure, not a cross-tenant RLS failure. Review analogous collection/document read routes for consistent metadata policy.

### QA2-05 — Verify citation occurrences, not just marker identities

Source: [citation verification](../../services/retrieval/src/nexiqon_retrieval/citations.py#L75).

Passage: `Backups run every night.`

Answer:

```text
Backups run every night [1]. Penguins pilot spaceships [1].
```

At support threshold 0.5, verification counts **1 supported / 2 cited sentences**, but returns both sentences with `[1]` intact. The global `supported_markers` set keeps every occurrence once any sentence supports that marker; the unsupported marker is also omitted from the removal list.

**Expected:** remove or flag the unsupported occurrence even when another occurrence of that marker is supported. Preserve supported citations and make the response/UI's removal information match the text.

### QA2-06 — The first matching chunk bypasses the context cap

Source: [section expansion fallback](../../services/retrieval/src/nexiqon_retrieval/search.py#L328).

Index a synthetic **375-token** chunk using the valid 400-token chunk size. Search with small-to-big expansion and **`max_context_tokens=256`** (the schema's minimum permitted cap). Returned passage tokens: **375**, exceeding 256.

When the first section does not fit, `_expand` only skips an oversized matching group if `passages` is already nonempty. The first group therefore bypasses the budget.

**Expected:** define and enforce behavior for an oversized first chunk/group, such as returning no passage or truncating safely with accurate token accounting. Test the first passage and later passages.

## Reproduction artifacts

The following files contain **expected acceptance assertions**. They intentionally fail on the reviewed implementation and are named so they do not join normal pytest discovery until maintainers promote the regressions into the service suites. Baseline collection remains **330 tests**.

- [Retrieval cases](reproductions/phase2_retrieval_cases.py): five failed assertions covering QA2-01 twice and QA2-04–06.
- [Ingestion cases](reproductions/phase2_ingestion_cases.py): two failed assertions covering QA2-02–03.

Run from the repository root with Docker available:

```bash
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase2_retrieval_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase2_ingestion_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
```

These reuse the existing real-Postgres/Temporal fixtures and use synthetic source content. The S3 case uses a real local HTTP socket with controlled DNS behavior. Raw outputs, baseline JUnit XML, the evaluation report and GitHub summaries are in [evidence/2026-11-09-phase-2](evidence/2026-11-09-phase-2/).

## CI and claim boundaries

Queried GitHub's public API independently. Latest branch runs matched the local branch tips and succeeded:

| Branch | Commit | Green run |
| --- | --- | --- |
| `phase-2/model-gateway` | `5dd5e6c` | [42446831089](https://github.com/aanaruna78/Nexiqon/actions/runs/42446831089) |
| `phase-2/ingestion` | `42cf99d` | [42496783087](https://github.com/aanaruna78/Nexiqon/actions/runs/42496783087) |
| `phase-2/retrieval` | `5bdca5d` | [42498874890](https://github.com/aanaruna78/Nexiqon/actions/runs/42498874890) |
| `phase-2/knowledge-ui` | `4e7bf06` | [42563212428](https://github.com/aanaruna78/Nexiqon/actions/runs/42563212428) |

The current-tip job summary confirms Python, Frontend, OPA, Security and Container image success. Breaking-contract comparison was skipped on the push run. Security/Storybook results were confirmed through CI; security scanners and Storybook were not independently rerun locally. Browser E2E is still absent from the CI workflow; its pass above is local.

The claimed counts, plugin/connector/parser/chunker source, ADR 0017, provider-interface structure, offline-provider opt-in, latency metric/dashboard/alert definition, evaluation CLI, Knowledge UI and Playground are present. The pypdf 6.21.4 exception is explicitly recorded in `services/ingestion/pyproject.toml`. This review confirms that record, not its release-age/CVE rationale independently.

Not established here: live OpenAI/Anthropic/Gemini or vLLM/Ollama interoperability, real-model evaluation M-07, production-scale concurrency/budget races, production deployment, full language/usability/mobile coverage, external S3/Git provider behavior, or actual firing of the Grafana alert under injected latency. Existing adapter/workflow unit/integration passes do not replace those checks.

## State and next acceptance gate

Only this QA report, reproduction cases and evidence were added. Application sources, branch history and deployment configuration were left unchanged. No merge or push was performed. Test-created tenants from existing smoke/browser suites remain in the development database. The additional live scanner collection and its files were deleted; its tenant remains (`phase2-qa-847c5474`). Disposable test containers/listeners and the image-smoke container were cleaned up by their fixtures/scripts. The local QA image tag remains available.

Fix the six findings, promote the reproduction assertions into maintained regression suites, and rerun the affected checks plus CI before Phase 2 acceptance. The green baseline and CI runs alone do not close these findings.
