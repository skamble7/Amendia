# Playwright UI e2e (primary e2e): report

## 1. Outcome

`webui/e2e/` is a **Playwright** suite that drives the real webui→backend stack as a user: logs in through
Keycloak (per persona, once), renders the cohort/instance screens, exercises the onboarding wizard's
condition-normalization banner, owner-gating and the DAG/SLA editor, resolves HITL gates **entirely through the
Task Inbox UI**, and proves **live SSE** updates. **Verified live against the running stack** (ACH onboarded): the
full arc — fire ACH → drive assess/enforce/closeout gates in the browser (SoD-aware personas, manual gates
authored via the raw-JSON form) → **cohort closes Released**, read off the Cohorts screen — passes. The pytest
smoke (`backend/tests/smoke/`) is left untouched as the fast headless layer; both reuse the same scenario specs.
**Zero webui source changes** were needed (all selectors use existing roles/labels/text) — no `data-testid` hooks.

## 2. Harness layout

- **`playwright.config.ts`** — `webServer: npm run dev` (vite dev, whose proxy sends `/api/*` to the compose
  backend via the `18xxx` `VITE_*_URL` defaults), `baseURL` = the served webui, `workers: 1` (shared backend
  state), traces/screenshots/video retained on failure, HTML report to `e2e/.report`.
- **`global-setup.ts`** — preflight the backend (down → write a skip flag, return; the suite skips cleanly), wait
  for the webui, then automate the **OIDC auth-code login once per persona** (priya/marcus/riya) through the
  Keycloak form and snapshot each persona's auth.
- **Auth model** — react-oidc keeps tokens in **sessionStorage** (which Playwright's `storageState` does NOT
  capture), so global-setup also snapshots `sessionStorage` to `e2e/.auth/<persona>.session.json`; the `page`
  fixture (`support/fixtures.ts`) re-injects it via `addInitScript` before the first nav. `support/personaPage.ts`
  opens a **fresh page as a specific persona** (used by the HITL arc so each gate is resolved by an SoD-correct
  actor within one test).
- **Page objects** (`pages/screens.ts`) — Cohorts, CohortDefinition, OnboardingWizard, TaskInbox + a
  `resolveTaskOnPage` that claims, authors the artifact via the raw-JSON editor, fills the required comment, and
  submits (variant-aware: "Complete task"/"Approve"/"Authorize all"). **Scenario reuse** (`support/scenarios.ts`)
  reads `backend/tests/smoke/scenarios/*.yaml`; `support/backend.ts` fires the trigger (pega_stub / stub_generator)
  and does read-only discovery of *which* gate is open + *who* may act (SoD) — plumbing; every claim/decide/form
  action happens in the browser.

## 3. Journeys + what each asserts

- **cohorts** — Instances tab lists cohorts with a state chip; Definitions tab lists `ach_exposure_cohort`; the
  SLA board renders when a cohort has SLA data.
- **onboarding-condition** — uploading a Camunda `${…}` BPMN in the technical wizard surfaces the **normalization
  banner** ("Converted 2 gateway conditions from Camunda", expandable to before `${decision == "Proceed"}` →
  after `decision == "Proceed"`).
- **owner-gating** — priya sees **Edit definition** + the Expectation-graph card; marcus sees the same definition
  **read-only** (two persona projects, one screen).
- **dag-sla-editor** — on a throwaway definition: add a node (no edges) → Save → the **server 422** ("not
  reachable") inline; wire `__start__→seg-a→__close__` → Save → read view shows the node. On the real ACH
  definition: Edit shows the **forward-only** warning + the live editor, then Cancel (no mutation).
- **hitl-arc** — fire ACH → for each waiting gate, open `/inbox/<taskId>` as an SoD-correct persona, **claim +
  author the artifact** (raw-JSON `release_authorization` / `review_decision`) + authorize — until the **cohort
  detail shows Closed / Released** (asserted from the UI). Full A→B→C→close, ~30s.
- **live-sse** — with the Instances list open and **not** reloaded, a fired case's instance row arrives live
  (notification-service relays `dispatch_accepted` → the browser invalidates `["instances"]` → refetch), via
  `expect.poll`.
- **instance-diagram** — a closed cohort renders its **per-member BPMN diagrams** highlighted (ADR-062), with the
  executed/current/not-taken/failed legend.

## 4. `data-testid` hooks added

**None.** Every selector uses existing ARIA roles, labels (`getByLabel("release_authorization raw JSON")` — an
`aria-label` already present), placeholders, or visible text. No webui source was modified (only `package.json`
gained the dev deps + the `e2e` script; `e2e/` is outside the webui `tsconfig` so `tsc`/build/vitest are
unaffected).

## 5. Launcher + deps + install

- **`tools/e2e.sh`** — checks deps, runs `npx playwright test` (pass-through args: `-g`, `--project`), prints a
  per-journey summary, non-zero on failure. **`npm run e2e`** = `playwright test`.
- **Deps** — `@playwright/test` + `js-yaml` (+ `@types/js-yaml`) as devDependencies (free/OSS). One-time browser:
  `npx playwright install chromium`.

## 6. Verification (live, against the running stack)

- `bash tools/e2e.sh` → **10 passed, 1 skipped, 38s, exit 0** — cohorts render, onboarding-condition banner,
  owner-gating (priya editor / marcus read-only), dag-sla-editor (save + 422 + forward-only), **hitl-arc (cohort
  Closed/Released driven entirely in the Task Inbox UI, ~32s)**, live-sse (instance row live), instance-diagram
  (ADR-062 member highlighting). The 1 skip is the optional "SLA board on a closed cohort" sub-assertion, which
  degrades cleanly when no SLA-carrying cohort row is clickable. `tsc --noEmit` clean; the webui `vitest`/`build`
  and the pytest smoke are untouched.
- **Degrade:** `INGESTOR=http://localhost:19999 npx playwright test` → global-setup writes the skip flag and every
  test skips with "stack not reachable". A **not-onboarded** pack → that journey skips ("onboard … first").

## 7. Follow-ups

- Fire via the **Triggers UI** instead of the stub API (fully in-browser trigger). Branch / SLA-breach journeys
  (ACH `late_closeout` → at-risk/breach chips on the cohort SLA board). CI wiring (ephemeral onboarded stack;
  Playwright's HTML report + traces as artifacts). **Test-data cleanup / correlation prefix** — the same pollution
  note as the pytest smoke: fired cases persist as closed cohorts. **Firefox/WebKit projects** (chromium only
  today). The known trade-off stands: browser e2e is slower/flakier than the pytest smoke — keep that as the fast
  pre-flight.
