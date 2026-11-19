# Phase 3 verification — 18 November 2026

**Verdict: testing completed; acceptance withheld.** The reported baseline counts are confirmed, but eight additional acceptance checks reproduce **six findings**. Four are P1 issues involving caller isolation, assistant scopes, confirmation enforcement and restricted-data handling. Application code was not changed.

## Reviewed state

- Branch: **`phase-3/gaps`**, HEAD **`dbf70734281e835decccbc998fc5bd379c5fe8a5`**.
- The reviewed implementation includes the **54 pre-existing modified/untracked gap-fix files**, not just HEAD. Their paths and SHA-256 hashes were recorded before testing. All 54 still matched at completion.
- These local changes include assistant-key restrictions, draft previews, access-count diagnostics, snippets, download links, dependency updates and the GPU/model-comparison additions.
- Backend tests used real disposable Postgres and the existing integration fixtures, with model/retrieval/business-API doubles where those fixtures provide them. Temporal/NATS/OPA tests ran as part of the baseline suite.
- Browser and gateway checks used the already-running development stack. Studio was initially absent on port 3100: the first browser attempt failed with connection refused. QA then started the freshly built Studio, reran successfully, and stopped that QA-owned process afterward. No application fix was needed for this setup issue.
- A new image was built from the working tree and smoke-tested in a temporary container. The full development stack was not rebuilt or replaced, so running-stack results are not proof that every container contained the exact reviewed gap fixes.

## Executed checks

| Check | Observed result |
|---|---|
| Frozen Python/pnpm installs | Pass |
| Python lint/format | Pass; 381 files formatted at baseline |
| Strict mypy | Pass; 237 source files |
| Architecture and OpenAPI freshness | Pass; zero architecture violations |
| Generated TypeScript client comparison | Pass; generated each contract into a temporary directory and compared bytes, preserving the user's uncommitted generated files |
| Full Python suite | **435 passed**, no skips, 2 deprecation warnings, 188.82 seconds |
| Frontend lint, types, unit tests and builds | Pass; **38 Studio + 11 widget = 49 unit tests** |
| Browser suite against real running stack | **23 passed**, 50.3 seconds, including EN/AR axe scans |
| OPA policy tests | **20 passed** |
| Existing gateway smoke | **26 checks passed**; predominantly foundation checks, not complete tool/agent acceptance |
| Offline retrieval quality gate | **29 cases**, Recall@5 **1.0**, evidence **1.0**, expansion P95 **43.92 ms**; pass |
| Source image build | Pass; `nexiqon/platform:phase3-qa`, local image ID `9c8b7dd4a5d8` |
| New image container smoke | `/healthz` and `/identity/meta`: **200**; UID **10001**; container removed |
| GPU Compose overlay | Configuration validates; no GPU containers or model downloads started |
| Model comparison CLI | `python -m tools.eval.model_bakeoff --help` succeeds; its unit tests are included in the full Python run |
| Widget production bundle | **13,113 gzip bytes**, consistent with the approximate 13 KB claim |
| Additional acceptance checks | **8 failed assertions across 6 findings**, detailed below; final runs have no fixture/setup errors |

The offline retrieval numbers measure machinery, not real-model answer quality. Axe passes cover visited screens and the suite's serious/critical threshold. The Arabic test visits Home, Knowledge, Playground, Assistants and the pack widget editor; it does not independently scan every new screen/state in Arabic.

## Findings

| ID | Priority | Finding |
|---|---|---|
| QA3-01 | **P1** | Tool idempotency replays return a different caller's result |
| QA3-02 | **P1** | Assistant-scoped keys bypass their scope through tools and conversation reads |
| QA3-03 | **P1** | A Domain Pack's higher write risk does not enforce confirmation |
| QA3-04 | **P1** | Restricted assistant answers are sent back to a cloud profile as internal history |
| QA3-05 | **P2** | Streaming discloses output that the final system-prompt guard withholds |
| QA3-06 | **P2** | Widget/non-staff callers receive staff-only hidden-source counts |

### QA3-01 — Bind replay identity to the verified caller

Sources: [invocation replay lookup](../../services/tool-gateway/src/nexiqon_tool_gateway/api.py#L186), [database uniqueness](../../services/tool-gateway/src/nexiqon_tool_gateway/models.py#L30).

In the real-config/Postgres tool fixture:

1. Customer A invokes `account-lookup` using idempotency key `shared-request-id` and empty arguments.
2. Customer B invokes the same tool with the same key and empty arguments.
3. B receives **`replayed=true`**, exactly A's account result. Only **one upstream request** was made.

The normal executor correctly substitutes `caller.actor_id`. The replay path bypasses that identity-dependent execution: its lookup and uniqueness constraint use tenant/tool/idempotency key without caller identity. The argument digest does not help because both users legitimately have identical arguments (`{}`). This is a same-tenant cross-customer disclosure, not a cross-tenant RLS failure. The second caller must know or guess the idempotency key; it must not function as authorization.

**Expected:** include verified caller identity in replay lookup and uniqueness, and reject mismatched ownership before returning any stored result. Bind other relevant execution context, including the assistant, so replay cannot cross security scopes. Preserve same-caller retry behavior and write idempotency tests.

### QA3-02 — Enforce assistant scope on all entry points

Sources: [tool checks](../../services/tool-gateway/src/nexiqon_tool_gateway/api.py#L94), [conversation loading](../../services/conversation/src/nexiqon_conversation/api.py#L89), [conversation listing](../../services/conversation/src/nexiqon_conversation/api.py#L174).

Two independently signed-context reproductions:

- An `api_key` with `agents={billing}` and an allowed inference/tool role invokes `account-lookup` with body `agent=support`. Observed: **200**, `ok=true`, business API called. The runtime run endpoint's `require_agent` check does not protect direct tool invocations.
- A `member` API key limited to `billing` reads a `support` conversation created by another actor. Observed: **200**, **two messages returned**; the unrestricted conversation list also includes it. Members may read all conversations under the role policy, but the key's additional assistant restriction should still constrain that permission.

The original gap fix checks scopes when creating conversations and running assistants, but the tool's shared `_checked` path and conversation read/list paths do not apply the claim.

**Expected:** require the allowed assistant before tool invoke/confirmation/dry-run operations, validate a loaded conversation's assistant before reads or mutations, and scope list queries. Audit trace/approval/replay paths for the same requirement. An actor's broad role must not override a narrower key scope.

### QA3-03 — Use effective risk for confirmation as well as permissions

Sources: [effective risk computation](../../services/tool-gateway/src/nexiqon_tool_gateway/api.py#L101), [confirmation branch](../../services/tool-gateway/src/nexiqon_tool_gateway/api.py#L207), [definition-only confirmation property](../../services/tool-gateway/src/nexiqon_tool_gateway/registry.py#L32).

Deploy a valid `create-ticket` tool definition with `risk_level=read`, `confirmation=never`, and a POST request to the synthetic case API. The real SaaS Knowledge Assistant pack independently declares **`create-ticket` as write/always-confirm**. Deploy an assistant allowing that tool.

Invoke with a valid idempotency key and no approval. Observed: **200**, `ok=true`, **one write request reaches the mock business API**.

`_checked` correctly raises the effective risk to the pack's stricter `write` value. That value is used for permission/idempotency checks, but confirmation depends only on `tool.needs_confirmation`, which sees the lower tool-definition risk. Thus the promised “stricter one wins” rule is only partially applied.

**Expected:** derive confirmation from the effective risk and applicable pack/tool confirmation rules; enforce it server-side and expose consistent effective requirements to the runtime's tool selection/approval flow. A pack's write classification must never be bypassed by a lower tool definition.

### QA3-04 — Preserve sensitivity when trusted answers become history

Sources: [conversation history construction](../../services/conversation/src/nexiqon_conversation/api.py), [smalltalk generation](../../services/agent-runtime/src/nexiqon_agent_runtime/nodes.py#L765), [argument extraction](../../services/agent-runtime/src/nexiqon_agent_runtime/nodes.py#L408).

Using the real conversation/runtime/config services on Postgres:

1. Mark a synthetic retrieved source `restricted` and produce an answer containing sentinel `RESTRICTED-QA-ALPHA`.
2. Verify that the first grounded generation call is correctly labelled **`restricted`**.
3. Send the ordinary follow-up **`hi`** through the conversation service.
4. The next smalltalk call uses **profile `cloud-frontier`**, **classification `internal`**, and includes the prior restricted answer in its history.

This is server-generated conversation history, not a caller supplying arbitrary text and choosing its own label. The current grounded-answer fix considers current sources, while later history-bearing generation paths use a fixed internal label. The model gateway cannot preserve restricted-data policy after that label is dropped.

The provider in the reproduction is a recording test double; no restricted material was sent to a real cloud provider.

**Expected:** persist trusted sensitivity with messages/checkpoints and label every downstream call at least as strictly as all included history/source/tool content. Alternatively omit or safely transform sensitive history before a lower-classification call. Cover smalltalk, clarification, tool argument extraction, summaries and mixed-source continuations.

### QA3-05 — Final withholding cannot undo earlier streamed disclosure

Sources: [raw delta forwarding](../../services/agent-runtime/src/nexiqon_agent_runtime/nodes.py#L716), [later output guard](../../services/agent-runtime/src/nexiqon_agent_runtime/nodes.py#L773), [conversation relay](../../services/conversation/src/nexiqon_conversation/api.py#L543).

The fixture's adversarial model is configured to repeat the system prompt when it sees a synthetic sentinel. Run a widget/end-user streaming turn.

Observed:

- Final checked answer: **`kind=withheld`**, as intended.
- Concatenated SSE `delta` events already contain the **entire 236-character system prompt**.

The guard detects the unwanted repetition, but only after `_generate` has forwarded it. Calling streamed text provisional and replacing it at completion does not retract bytes already delivered. The text-only widget avoids HTML/image execution, but does not prevent this disclosure to the caller.

**Expected:** apply required withholding guarantees before releasing protected output, or explicitly redesign the streaming/guard contract with a safe buffering strategy. Include adversarial checks over the complete SSE event sequence, not only the final answer. The current public pack prompt in this test is synthetic/non-secret; no production credential was exposed.

### QA3-06 — Apply staff-only diagnostic policy at every response boundary

Sources: [unrestricted diagnostic search](../../services/retrieval/src/nexiqon_retrieval/api.py#L429), [runtime step enrichment](../../services/agent-runtime/src/nexiqon_agent_runtime/nodes.py#L366), [GET-trace filtering](../../services/agent-runtime/src/nexiqon_agent_runtime/api.py#L184).

Two reproductions:

- A widget with no access groups calls retrieval search with `explain_access=true` against a collection containing a restricted payroll document. Search returns **200**, **zero visible passages**, **`hidden=1`**.
- A widget/end-user runtime turn receives **`steps[].hidden_by_access=7`** in the immediate run response when the retrieval double supplies that synthetic count.

The GET trace helper strips the diagnostic field for non-staff. Immediate `RunOut` responses and streaming final results bypass that helper, and retrieval itself allows the count request. This contradicts the summary's staff-only count requirement and reveals the existence of matching hidden content. The count is query/top-k dependent; it is not a complete inventory of inaccessible documents.

**Expected:** authorize count computation separately and redact diagnostics consistently from retrieval, immediate runs, stream results, and stored/conversation contracts delivered to non-staff. Keep the staff Inspector behavior covered by positive tests.

## Reproduction files and evidence

The additional acceptance files are deliberately named outside normal pytest discovery. They assert expected behavior and **currently fail**; they do not change the passing baseline suite. Promote them into maintained regression tests when fixing the findings.

| File | Findings | Final result |
|---|---|---|
| [phase3_tool_cases.py](reproductions/phase3_tool_cases.py) | QA3-01, QA3-02, QA3-03 | **3 failed assertions** |
| [phase3_conversation_cases.py](reproductions/phase3_conversation_cases.py) | QA3-02, QA3-04 | **2 failed assertions** |
| [phase3_agent_cases.py](reproductions/phase3_agent_cases.py) | QA3-05, QA3-06 | **2 failed assertions** |
| [phase3_retrieval_cases.py](reproductions/phase3_retrieval_cases.py) | QA3-06 | **1 failed assertion** |

Run each from the repository root, with Docker available:

```bash
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase3_tool_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase3_conversation_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase3_agent_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase3_retrieval_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
```

All cases use synthetic data and local test fixtures. Evidence, baseline JUnit XML, the starting file-hash manifest and CI summaries are in [evidence/2026-11-18-phase-3](evidence/2026-11-18-phase-3/).

## CI and limits of verification

Independently queried GitHub's public API. Latest pushed slice runs are green:

| Branch | Tested commit | Run |
|---|---|---|
| `phase-3/agent-runtime` | `d854bc9` | [42571912550](https://github.com/aanaruna78/Nexiqon/actions/runs/42571912550) |
| `phase-3/tool-gateway` | `65ecf35` | [43415514845](https://github.com/aanaruna78/Nexiqon/actions/runs/43415514845) |
| `phase-3/channels-streaming` | `d11d258` | [43421850384](https://github.com/aanaruna78/Nexiqon/actions/runs/43421850384) |
| `phase-3/studio` | `dbf7073` | [43427430341](https://github.com/aanaruna78/Nexiqon/actions/runs/43427430341) |

`phase-3/gaps` has **no workflow run**. Those green runs do not include its 54 uncommitted gap fixes. Security scans were not independently rerun locally; existing CI success cannot certify the later local changes. Browser E2E remains a local check rather than a CI job.

The new ADRs, guardrail merge change, guided-JSON path, LangGraph validation/checkpointing, tool controls, OpenBao adapter, streaming/channel/widget implementation, Studio screens, snippets, signed-download implementation, GPU guide and comparison CLI are present and covered to varying degrees by the existing suites. This report does not establish production safety from those passes alone.

Not established here: live external business APIs/OpenBao operations under production policy; live OpenAI/Anthropic/Gemini or vLLM/Ollama interoperability; real GPU model serving/licence compliance; real-model M-07 quality; distributed rate limiting or concurrency/idempotency crash recovery; production retention/load behavior; complete multilingual, assistive-technology or mobile usability coverage. Release-age/CVE rationales for dependency upgrades were not independently researched.

`git diff --check` also reports pre-existing extra blank lines at EOF in four user-modified files (`sources.tsx`, `playground.tsx`, `studio.test.ts`, ingestion README). They were left untouched; these are hygiene notes, not additional security findings.

## Completion state and acceptance gate

Only this QA report, explicit reproduction cases and evidence were added. **All 54 original modified/untracked files remained byte-for-byte unchanged.** No commit, merge, push, application fix, change to existing credentials or stack rebuild was performed. Existing smoke/browser tests created development tenants and related test records under their normal behavior; no real customer accounts were used. Disposable integration containers and the temporary image-smoke container were cleaned up, and the QA-started Studio process was stopped. The local QA image tag remains available.

Fix the six findings, add regression coverage for their response/security boundaries, commit the gap fixes, and obtain green CI on that exact result before Phase 3 acceptance.
