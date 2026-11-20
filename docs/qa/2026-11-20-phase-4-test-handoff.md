# Phase 4: test handoff (20 November 2026)

Phase 4 is complete in nine slices, all merged to `main` at **`6077d73`**. Each slice passed CI
before it was merged. This page lists what to test, how, what to expect, and what is out of
reach without credentials or hardware.

| Slice | Commit | Backlog items | ADR |
|---|---|---|---|
| 1. Deployment preview | `b87b4e4` | DV-02, DV-03, ST-13, ST-15 | — |
| 2. Quality | `7e90235` | QA-01, QA-02, ST-17, ST-14 | 0021 |
| 3. Widget product | `f6235ae` | W-01..W-04, NT-01 (email) | 0022 |
| 4. Operate | `83ae2de` | MT-01, MT-02, ST-18, ST-16 | 0023 |
| 5. Governance | `a99f3d7` | G-01, G-02, G-03, NT-01 | 0024 |
| 6. Security | `6735886` | S-01, S-02, S-03, DV-01 | 0025 |
| 7. Deployment modes | `88f1296` | DV-04, DV-08, DV-07 | 0026 |
| 8. Installs | `8422f3a` | DV-05, DV-06, DV-09, DV-03b | 0027 |
| 9. Quality bar | `6077d73` | UX-10, UX-11, D-01 | 0028 |

## Setup

```bash
git checkout 6077d73
make setup
make dev-up PROFILES=platform,apps          # add ,observability for Grafana; ,scan for ClamAV
make studio                                 # Studio on http://localhost:3100 (dev / dev-password)
```

Mail sent by the local stack (transcripts) appears in Mailpit at http://localhost:8025.

## Baseline (developer runs at `6077d73`)

| Check | Command | Result |
|---|---|---|
| Lint, types, architecture, contracts, Python tests | `make check` | 526 passed |
| Studio and widget unit tests | (in `make check`) | 65 + 23 passed |
| OPA policy tests | `docker run … opa test services/authz/policies` | 28 passed |
| Browser end-to-end tests, real stack | `pnpm exec playwright test e2e/studio.spec.ts` | 34 passed |
| Accessibility audit, 4 languages × themes | `pnpm exec playwright test e2e/a11y-audit.spec.ts` | 126 scans, 0 findings |
| Visual regression | `make visual` | 42 passed |
| Helm render, kubeconform, Envoy validation | CI "Deployment" job | all profiles valid |
| OpenTofu validate (DO, AWS, GCP, Azure) | CI "Deployment" job | valid |
| Docs site, strict | `make docs` | builds, no warnings |

**Please re-run these from a clean checkout first**, and record the numbers in your verification
report.

---

## Slice 1: Helm chart, cloud module, setup guide, widget settings

**What to test:**

1. **Setup guide.** In Studio, open **Get started**:
    - choose a pack from the gallery;
    - create a collection and upload a file, or crawl a site;
    - create an assistant and ask a question;
    - copy the embed code.

   Expected: each step turns done as soon as its condition is met.
2. **Widget settings.** On an assistant, open the **Widget** tab:
    - change the title, greeting and colour, then save and release;
    - list allowed websites and create a widget key.

   Expected:
    - the key is shown once;
    - it works only from the listed origins, and only for that assistant;
    - an origin that is not a URL is rejected with an explanation.
3. **Chart.** Install into kind with `uv run python tools/dev/kind_up.py`. This needs kind,
   kubectl and helm on the machine.

**Automated:** `tools/lint/test_helm_chart.py`, `services/channel/tests/test_channels.py`, and the
e2e scenarios "setup guide…" and "assistants: widget text and colour…".

**Known limits:**
- The kind cluster run has not been done on a developer machine.
- The DigitalOcean module has never been applied (no credentials).

## Slice 2: evaluations, safe publish, fix loop

**What to test:**

1. **Evaluations.**
    - Create a test set from a pack (cases come with it), and add your own case with expected
      phrases and a source.
    - Run it against the live version and a draft.

   Expected:
    - a scorecard with the pass rate, per-check scores, per-language results, latency and cost;
    - every case links to "Why this answer" (the Inspector).
2. **Safe publish.** On an assistant's **Quality** tab:
    - require a passing evaluation, then try to publish a draft that was not evaluated.

      Expected: blocked, with the reason.
    - Evaluate it, then publish.
    - Change the draft after evaluating it.

      Expected: blocked as "changed since evaluation".
    - As an admin, publish anyway with a reason of 10 or more characters.

      Expected: the reason appears in the audit log.
3. **Fix loop.** From any answer, choose **Fix**:
    - add a reviewed answer;
    - mark a source outdated (it leaves answers at once);
    - ask again;
    - save the question to a test set.

**Automated:**
- `services/evaluation/tests/*`;
- `services/retrieval/tests/test_search.py` (outdated sources);
- e2e "evaluations…", "fix loop…" and "safe publish…".

**Watch for:**
- a run against one tenant must never see another tenant's documents;
- an evaluation run never calls tools.

## Slice 3: the website widget

**What to test** (embed the widget on a page of your own; see the README in
`frontend/apps/widget/`):

- **Appearance:**
    - light, dark and auto themes;
    - floating and inline modes;
    - the pack's words and colour (low-contrast colours are adjusted).
- **Languages:** en, es, fr, de and ar. Arabic is fully right-to-left.
- **Answers:**
    - each answer streams in, then shows its sources;
    - weak answers show **Not sure**, with one-tap handover;
    - actions that change data show a confirmation card, and nothing happens without a tap.
- **Feedback:** thumbs up or down; thumbs down asks "what was missing?". Suggested follow-up
  questions appear after an answer.
- **Email me a copy:** the transcript arrives in Mailpit. Per-recipient limits apply.
- **Keyboard and screen reader:**
    - Esc closes the widget and returns focus to the launcher;
    - each finished answer is announced once, not word by word.

  The walkthrough is in `docs/guides/widget-accessibility.md`.
- **Size:** the build prints the gzipped size: 18 KB, against a budget of 60 KB.

**Automated:**
- `frontend/apps/widget/test/nexiqon-chat.test.ts`;
- `services/conversation/tests/test_transcripts.py`;
- `services/notification/tests/test_email.py`;
- the e2e scenario "widget on a customer's site…";
- visual screenshots of the widget (slice 9).

**Fixed in slice 9:** a blank gap before every answer, and gaps around the sources. Please check
it on a real page.

## Slice 4: metering, insights, escalation queue

**What to test:**

1. **Escalation queue.** Ask for a person in the widget. In **Conversations → Waiting for a
   person**:
    - claim the conversation, reply, and resolve it;
    - j and k move between conversations.

   Expected:
    - the visitor sees the staff reply in the widget;
    - the assistant stays quiet in that conversation;
    - the notification bell shows the handover.
2. **Insights.**
    - Answer rates against the previous period.
    - Pack KPIs.
    - Content gaps: unanswered or escalated questions grouped by topic. **Answer this** opens the
      fix loop.
    - Cost by assistant and by model; it should match the model gateway's records.
3. **Budgets.** Set a monthly budget below the current spend. Expected: alerts at 50, 80 and
   100%, in the inbox (and by webhook, slice 5).

**Automated:**
- `services/metering/tests/test_metering.py`;
- `services/conversation/tests/test_queue.py`;
- `frontend/apps/studio/test/operate.test.ts`;
- e2e "conversations…", "insights…" and "notifications…".

## Slice 5: data export, retention, deletion, backups, webhooks

**What to test** (in **Settings → Organization → Data and deletion**):

1. **Export.** Prepare an export, then download it. Expected:
    - one archive with every service's data;
    - no secrets in it;
    - the archive is kept 7 days.
2. **Retention.** Choose **Run now**. Expected:
    - expired conversations, traces and tool results are removed;
    - the result is recorded and audited;
    - unreachable services are listed.
3. **Deletion.**
    - Type the slug to confirm. Expected: deletion is scheduled with a 72-hour grace period;
      cancel works.
    - Let a deletion run; the dev stack uses a short grace period. Expected:
        - no rows remain in any service;
        - a certificate lists which services confirmed it.
    - **Check another tenant's data is untouched.**
4. **Webhooks** (**Settings → Webhooks**):
    - Only public HTTPS URLs are accepted (try `http://`, `localhost` and private IPs).
    - Signatures verify with the shown secret (`X-Nexiqon-Signature`: `t`, `v1`).
    - **Send test** works.
    - Repeated failures switch the endpoint off.
5. **Backup drill.** Run `uv run python -m tools.ops.backup_drill`. Expected: a JSON report in
   which every table's row count matches after the restore.

**Automated:**
- `services/governance/tests/test_lifecycle.py`;
- `services/notification/tests/test_webhooks.py`;
- e2e "organization data…" and "webhooks…".

Runbook: `docs/runbooks/backup-restore.md`.

## Slice 6: security hardening, alerts, images

**What to test:**

- **Headers:**
    - Studio sends a CSP (`default-src 'self'`), `frame-ancestors 'none'`, COOP, and HSTS in
      production.
    - The gateway adds `nosniff`, `X-Frame-Options: DENY` and `no-referrer`, and drops the
      `server` header.
- **Log redaction.** Send emails, phone numbers, card numbers, bearer tokens or `nxq_` keys in
  messages and requests. None may appear in container logs.
- **Rate ceiling.** Flood the gateway. Expected: 429 above the per-pod ceiling.
- **Images.** Each image is non-root (UID 10001), has no pip, no setuid binaries, and no shell
  entry point. Trivy finds no HIGH or CRITICAL issues.
- **Network policies** (chart): default deny, and no access to `169.254.169.254`.
- **Alerts:** run `promtool test rules deploy/observability/prometheus-rules.test.yaml`. Every
  alert has a runbook in `docs/runbooks/alerts.md`.
- **Threat model:** review `docs/security/threat-model.md`. Each threat names the test or check
  that proves its mitigation; please spot-check those proofs.

**Automated:**
- `libs/nexiqon-core/tests/test_logging_redaction.py`;
- e2e "security headers…";
- the CI image scan and promtool steps.

## Slice 7: hybrid data plane, split-origin Studio, region cells

**What to test:**

- **No content to the control plane.** `services/conversation/tests/test_hybrid.py` asks a
  question containing a marker phrase. The control plane must receive only
  `GET /v1/snapshots/<env>` requests, without the phrase. The same test shows answers still work
  from the cache when the control plane is down.
- **Key isolation:**
    - only the group running identity and config mounts `secrets.yaml` (the private signing
      keys);
    - every other group gets `public-keys.yaml`;
    - `tools/lint/test_helm_chart.py` enforces this in the chart;
    - on a single-node install, `docker compose -p nexiqon exec agent ls /app/keys` must not list
      `secrets.yaml`, while `control-core` must;
    - the dev compose stack is not a check: it mounts its whole config folder into every group, and
      only `NEXIQON_CONFIG_FILES` picks the files each group reads.
- **Config mirror permissions.** `service:config-mirror` may only read snapshots (OPA test).
- **Gateway** (render the chart with `values/hybrid-data.yaml`):
    - `/config-mirror/` and `/authz/` return 404 from outside;
    - the control-plane link accepts only its allowlisted paths.
- **Split-origin Studio** (`server.test.ts`):
    - CORS is allowed for the peer origin only;
    - cookies are `SameSite=None` only across sites;
    - after sign-in, return addresses are limited to the peer origin.
- **Region cells:**
    - identity returns `x-nexiqon-region`;
    - a client-sent copy of that header is stripped.

**Known limits:**
- No two-cluster run has been done; the chart was rendered and validated only.
- Evaluations and content gaps do not work for hybrid tenants yet.
- Data-plane audit events are not forwarded yet.

## Slice 8: single server, air-gapped, licence, minimal profile, cloud modules

**What to test:**

1. **Single server** (`deploy/single-node/README.md`):

   ```bash
   cd deploy/single-node
   ./install.sh --host <name> --oidc-issuer <your IdP>
   ```

   Use a spare machine. On a machine with less than 16 GB of memory, add `--force`. Expected:
    - every service is healthy;
    - Studio is served on 443 and the API on 8443, with TLS;
    - `/authz/` and `/config-mirror/` return 404;
    - running it again keeps passwords and data.

   Then:
    - `./backup.sh` writes a backup;
    - restarting OpenBao unseals it by itself;
    - the tool gateway's token cannot reach admin APIs.
2. **Air-gapped bundle:**
    - Build it with `uv run python -m tools.bundle.build_bundle --version X --airgap`.
    - Unpack it on another machine and run `install.sh --offline`. Expected: it installs with no
      registry access.
    - Change one file in the bundle. Expected: the install is refused ("checksums do not match").
3. **Licence:**
    - Make a test vendor key with `tools/licence/issue.py keygen`, issue a licence, and install
      with `--licence`.
    - A forged licence must stop identity.
    - With an expired licence (past the grace period), staff sign-in must fail with a clear
      message, but widget and API keys must still answer.
    - Creating organizations beyond `max_tenants` must be refused.
    - Only admins may see `GET /identity/v1/licence`.
4. **Minimal profile:** `values/minimal.yaml` renders and validates. Sizing is in
   `docs/guides/minimal-footprint.md`.
5. **Cloud modules:** `tofu validate` for AWS, GCP and Azure. Azure Blob storage is tested against
   Azurite (`libs/nexiqon-core/tests/test_azure_blob.py`).

**Automated:**
- `libs/nexiqon-core/tests/test_licence.py`, `test_keys.py` and `test_azure_blob.py`;
- `services/identity/tests/test_licence.py`;
- `tools/bundle/test_bundle.py`;
- `tools/lint/test_helm_chart.py`;
- CI checks that the single-node gateway config matches the chart, and runs shellcheck.

**Known limits:**
- GPU (vLLM) paths have not run on real GPUs.
- No cloud module has been applied.
- The single-node install brings no identity provider.

## Slice 9: accessibility, languages, visual regression, budgets, docs

**What to test:**

- **Languages.** Switch Studio to Français and Español in the account menu or the command
  palette, and check that no English remains.
    - Expected: placeholders and plurals read naturally.
    - Please flag poor translations; no linguist has reviewed them yet.
- **Accessibility.** Re-run the audit spec. A manual screen-reader pass (NVDA, VoiceOver) is
  **wanted and not yet done**.
- **Visual regression.** Run `make visual`. To check it catches changes, alter a colour in
  `globals.css` and expect failures with diff images. Accept intended changes with
  `make visual-update`.
- **Budgets.** `pnpm --filter @nexiqon/studio build` prints the JavaScript per route (the largest
  is 314 KB against 350 KB) and the CSS (23 KB against 28 KB). Exceeding either fails the build.
- **Docs.** Run `make docs-serve` and open http://localhost:8001. Check:
    - the quickstart, the pack and plugin SDK guides, the API reference and the install guides;
    - that no internal documents (plans, QA, ADRs) are published.

**Automated:**
- `test/theme-i18n.test.ts` (language parity);
- `e2e/a11y-audit.spec.ts`;
- `visual/*.visual.ts`;
- `tools/docs/test_docs.py` (the API reference matches the contracts).

Audit report: `docs/qa/2026-11-20-accessibility-audit.md`.

---

## Needs credentials, hardware or a decision (not testable here)

| Item | Needs |
|---|---|
| Apply OpenTofu (DigitalOcean, AWS, GCP, Azure) | Cloud credentials and the owner's go-ahead |
| Publish signed images, publish the docs site | The repository variables `PUBLISH_IMAGES` and `PUBLISH_DOCS` (the owner's decision) |
| vLLM on GPUs (single node `--gpu`, chart `models`) | NVIDIA GPU hardware |
| Hybrid across two real clusters, region cells | Two clusters and the link certificates |
| Production licence | The vendor key, made offline by the owner |
| External penetration test, screen-reader pass, translation review | External specialists |

## Suggested order

1. **Baseline:** re-run the table above.
2. **Isolation and data safety, highest risk first:**
    - deletion residue across tenants (slice 5);
    - the hybrid egress test (slice 7);
    - key isolation (slices 7 and 8);
    - licence enforcement (slice 8).
3. **Customer-facing flows:**
    - the widget on a real page (slice 3);
    - the escalation queue (slice 4);
    - safe publish (slice 2).
4. **Installs:** single node and air-gapped on a spare machine (slice 8).
5. **Quality bar:** languages, visual regression, budgets and docs (slice 9).
