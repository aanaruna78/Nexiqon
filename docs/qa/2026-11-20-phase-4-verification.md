# Phase 4 local QA verification — 20 November 2026

**Verdict: local verification completed; acceptance withheld for four reproduced defects.** The reported automated baseline is confirmed. Passing baseline tests and CI do not close the additional deletion, retention, licence-provisioning and safe-publish findings below.

## Scope and boundaries

Reviewed **`6077d73b0130ea1da4941c941abe9082de629f2e`**, checked out on `phase-4/quality-bar`.
GitHub confirms that remote `main` is at the same commit. The local `main` reference is stale; it was not moved. Tracked source files were initially clean; the only pre-existing untracked file was the Phase 4 handoff, whose bytes were preserved.

Local suites, disposable database/workflow fixtures, the existing development stack, temporary image/proxy containers, rendered manifests and temporary OpenTofu directories were used. No cloud credentials were provided to the validation containers. **No cloud changes, publishing, commits, merges or pushes were performed.** No production tenant, production licence or real GPU was used.

## Confirmed local results

| Check | Observed result |
|---|---|
| Python lint and formatting | Pass; 510 files formatted at baseline |
| Strict mypy | Pass; 290 source files |
| Architecture and OpenAPI freshness | Pass; zero architecture violations |
| Generated TypeScript types | Byte-for-byte match when generated into a temporary directory; tracked files not overwritten |
| Full Python suite | **526 passed**, no skips, 3 deprecation warnings, **260.66 seconds** |
| Frontend lint, types, units and builds | Pass; **65 Studio + 23 widget tests** |
| Build budgets | Pass; CSS **23.1 KB** against 28 KB; route JavaScript checks pass against 350 KB |
| Browser customer/admin flows | **34 passed**, **1.9 minutes**, against the running stack |
| Accessibility audit | **6 runs**, **126 page scans**, **0 findings**, **5.1 minutes** |
| Visual regression | **42 passed**, **7.1 seconds**, pinned Playwright image |
| OPA policies | **28 passed** |
| Existing gateway smoke | **26 checks passed** |
| Docs | Strict build passes; built output has no `plan`, `qa`, `adr`, `security` or `runbooks` directories |
| Helm configuration | **7 profiles rendered**, **284 Kubernetes resources valid**, zero schema errors/skips; no cluster contacted |
| OpenTofu | Format and initialization without a backend, then validation: **DigitalOcean, AWS, GCP, Azure and staging all pass**; no plan/apply |
| Alert rules | `promtool test rules` passes |
| Single-node shell scripts | Shellcheck passes |
| Signing-key isolation | Existing chart ownership/hybrid tests pass; independent single-node manifest inspection finds private `secrets.yaml` mounted only by **control-core** |
| Bundle integrity | Clean staged manifest verifies; deliberately altered VERSION is refused by the actual installer before image loading/configuration writes, with Docker mutations blocked by a test stub |
| Fresh platform image | Build passes; **UID 10001**, pip absent, no setuid/setgid files, non-shell entry point; health endpoint **200** |
| Hardened gateway, isolated container | Required response headers present, `server` absent; `/authz/` and `/config-mirror/` return **404** |
| Rate ceiling on that isolated gateway | 1,000 local health requests produced **520 HTTP 200 / 480 HTTP 429**; existing gateway was not flooded |
| Local backup drill | Success: **69 tables**, **30,414 source rows**, **2.97 seconds** total, no reported missing rows; scratch database removed |
| Additional acceptance checks | **4 failed assertions**, one per finding below; final runs have no fixture/setup errors |

The browser suite exercises setup, widget settings/origin scoping, evaluations, fix loop, safe publish, widget feedback/transcripts, handover queue, insights/budgets, notifications, organization lifecycle, webhooks, headers and language navigation. It is automated coverage of those scenarios, not exhaustive manual or specialist validation.

The accessibility runs cover English light/dark, French light, Spanish light and Arabic light/dark; every recorded axe finding is counted, and the suite fails on serious/critical findings. Zero findings does not establish screen-reader usability or translation quality. Visual baselines were **not updated** or intentionally changed during this verification.

The backup utility checks that restored counts are **at least** the pre-dump counts, allowing concurrent inserts; its success is not a byte-for-byte database comparison. The initial source was only read and dumped; the restore used its separate scratch database. Existing browser activity can affect source row counts.

## Highest-risk checks

- **Tenant deletion:** the existing real-service fixture confirms other-tenant table data survives. The additional export-archive check reveals incomplete cleanup despite a successful certificate (QA4-01).
- **Hybrid egress:** both existing hybrid conversation tests pass, including recorded control-plane requests and cache operation during an outage. This is a local fixture with fake model/retrieval services, not a two-cluster certification.
- **Private keys:** chart checks and single-node manifest mounts satisfy the configuration-level isolation rule. The development Compose stack deliberately mounts its config directory broadly and was not used as runtime proof of production key isolation. A real single-node/cluster installation remains untested here.
- **Licensing:** existing invalid/expired/test-key checks pass. The new Clerk provisioning test exceeds the licensed tenant limit (QA4-03). No production vendor key was needed or used.

## Findings

| ID | Priority | Finding |
|---|---|---|
| QA4-01 | **P1** | Completed tenant deletion leaves its previously generated export archive in object storage |
| QA4-02 | **P1** | Tool-result retention skips confidential results when the original arguments were empty |
| QA4-03 | **P2** | Signed Clerk organization events provision tenants beyond the licence limit |
| QA4-04 | **P1** | Concurrent draft edits can publish unevaluated bytes under a passing release-gate verdict |

### QA4-01 — Delete exported copies as part of tenant deletion

Sources: [governance's own lifecycle](../../services/governance/src/nexiqon_governance/runner.py), [archive creation and cleanup](../../services/governance/src/nexiqon_governance/runner.py).

Using the existing real-Postgres/Temporal governance fixture:

1. Seed tenants A and B.
2. Export A and confirm its ZIP exists at `t/<A>/exports/<request>.zip`.
3. Store a separate synthetic export marker under tenant B.
4. Run A's deletion through the grace period and service workflow.

Observed: deletion reports **`completed`**, the old export ZIP for A **still exists**, and B's marker is correctly untouched. The retained archive contains copies of the service data that the deletion purported to remove.

`Runner.own()` deletes retention/outbox rows but does not remove the tenant's exported objects. Retained lifecycle request records also continue to reference the archive. The existing age-based export purge is separate; waiting for a later retention sweep is not completion of tenant deletion.

**Expected:** delete tenant-owned archives and any incomplete export parts before certifying completion, clear downloadable references, and include object-store residue in the certificate check. Preserve only an appropriately minimal deletion certificate. Test deletion after both successful and partially failed exports, while retaining other tenants' objects.

### QA4-02 — Empty arguments must not exempt a stored result from retention

Source: [tool-gateway retention](../../services/tool-gateway/src/nexiqon_tool_gateway/lifecycle.py).

In the tool-gateway fixture, invoke the real configured account lookup with `{}` arguments, age the stored call by 90 days, and run retention with `tool_results_days=1`.

Observed: **`tool_results=0`** purged; arguments are empty, but the old account **result is still stored**.

The update predicate requires `ToolCall.arguments != {}`. A zero-argument tool correctly derives identity from the caller and can return confidential data; it therefore starts with empty arguments and never matches this purge condition.

**Expected:** purge expired results regardless of whether arguments were supplied, while retaining only the intended audit metadata. Cover empty/non-empty arguments, null/non-null results and repeat sweeps.

### QA4-03 — Apply tenant allowance to all provisioning paths

Sources: [self-serve licence check](../../services/identity/src/nexiqon_identity/api.py), [Clerk organization upsert](../../services/identity/src/nexiqon_identity/webhooks.py).

Create one organization in the identity fixture and set the same synthetic valid test licence style used by existing tests, with **`max_tenants=1`**. Deliver a correctly signed Clerk `organization.created` event for another organization.

Observed: **HTTP 200**, `status=processed`; a database count confirms **2 persisted tenants**. The webhook's direct tenant-creation path never applies `_check_tenant_allowance`.

This is a provisioning/entitlement bypass, not a forged licence or unsigned-webhook bypass. Clerk membership events can also call the organization-upsert helper, so they need the same policy.

**Expected:** share an allowance check across self-serve and IdP-driven provisioning, with atomic enforcement under concurrent creates. A processed/acknowledged provider event must not silently provision beyond the allowance. Test both organization and membership events and preserve idempotent retries.

### QA4-04 — Bind publishing atomically to the evaluated draft hash

Sources: [release-gate check and publish](../../services/config/src/nexiqon_config/api.py), [store publication](../../services/config/src/nexiqon_config/store.py).

The reproduction uses the real evaluation/config services, real Postgres and Temporal, and the existing scripted agent evaluator:

1. Evaluate a gated draft successfully.
2. Start publication as an editor.
3. Instrument the gate client so that, immediately after its real successful check, a second legitimate request edits that same draft and commits a different display name.
4. Return the original passing verdict and let publishing finish.

Observed: publication returns **HTTP 200**, **`gate.passed=true`**, and the published version contains **`Unreviewed QA change`**, which was not the content approved by the check.

The check reads the candidate hash in one transaction, awaits evaluation, then publication re-reads the mutable draft in another transaction without comparing the checked hash. The existing sequential “changed since evaluation” test cannot detect an edit in this interval.

**Expected:** bind the verdict to the hash/version actually published and reject concurrent changes (for example, with transactional locking plus hash comparison or an optimistic compare-and-swap). Keep the evaluation network call outside long locks if necessary, but revalidate before committing publication. Admin overrides should remain explicit and audited.

## Reproductions and evidence

These files contain expected acceptance assertions and **intentionally fail on the reviewed implementation**. Their names keep them outside normal pytest discovery; they should become maintained regressions when the fixes are implemented.

- [phase4_governance_cases.py](reproductions/phase4_governance_cases.py) — QA4-01.
- [phase4_retention_cases.py](reproductions/phase4_retention_cases.py) — QA4-02.
- [phase4_identity_cases.py](reproductions/phase4_identity_cases.py) — QA4-03.
- [phase4_evaluation_cases.py](reproductions/phase4_evaluation_cases.py) — QA4-04.

Run from the repository root with Docker available:

```bash
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase4_governance_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase4_retention_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase4_identity_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
PYTHONPATH="$PWD" uv run pytest docs/qa/reproductions/phase4_evaluation_cases.py -c pyproject.toml -p nexiqon_core.pytest_plugin -s -q
```

Raw outputs, baseline JUnit XML, the accessibility JSON and deployment/security-check scripts are in [evidence/2026-11-20-phase-4](evidence/2026-11-20-phase-4/). Reproductions use synthetic data and disposable fixtures, not real tenants in the development database.

## CI, environment limits and remaining work

GitHub confirms remote `main` at the reviewed SHA and a successful [main CI run 44663373430](https://github.com/aanaruna78/Nexiqon/actions/runs/44663373430). Python, Frontend, Deployment, OPA, Security and Container image jobs succeeded. Breaking-contract comparison, image publishing and docs publishing were skipped. Local source/image security scans were not independently repeated; the hardening checks above are separate from vulnerability scanning.

The following remain outside this local verification:

| Item | Required environment or decision |
|---|---|
| Apply any cloud module | Credentials and explicit approval; validation was completed without applying |
| Real GPU serving/performance and real-model evaluation | GPU hardware/model environment |
| Hybrid/region behavior across real clusters | Two clusters, link certificates and routing setup |
| Publish images, docs or a shareable Page | Explicit publishing decision |
| Production licence validation | Owner-held vendor key and production licence |
| Full single-node install/reinstall/reboot, real air-gapped install, OpenBao restart/unseal | Spare isolated host/environment; current stack was not replaced |
| kind installation | kind/kubectl/helm tooling and a local cluster; only render/schema checks were run here |
| Penetration testing, screen-reader assessment, natural-language quality | Appropriate outside specialists |

Additional limits: no deliberate visual-baseline mutation/update or over-budget build was performed; no exhaustive live PII-in-container-logs exercise was performed (the existing redaction tests passed). The live gateway/browser checks used existing backend containers, while the fresh platform image was tested separately. Dev Compose does not contain the same hardened edge filters as the generated installation gateway; header/rate-limit checks therefore used an isolated container with the generated gateway config.

## Completion state

Only QA report/reproduction/evidence files were added. Application source, chart/module source, the original handoff and visual baselines were not changed. The initial source tree was clean, and it remains free of tracked changes. Existing local Studio/backend services were left running. Temporary QA image/proxy containers and scratch test resources were removed; the local QA image tag remains available. Normal browser/smoke suites leave synthetic development records according to their existing behavior.

No cloud change, full installation, publishing, commit, merge or push was performed. Fix and retest QA4-01 through QA4-04 before local Phase 4 acceptance; passing CI and baseline suites alone do not close them.
