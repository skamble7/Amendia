# Claude Code prompt — **Playwright** UI e2e for the webui (broad journeys, HITL-via-UI, live SSE)

Author a **Playwright** end-to-end suite that drives the real **webui → backend** stack as a user: log in through
Keycloak, drive process scenarios to their terminal outcome **entirely through the UI** (including resolving HITL
gates in the Task Inbox), and assert the cohort/instance screens, the onboarding wizard, owner-gating, the DAG/SLA
editor, and **live SSE** updates. This is the **primary e2e** (Playwright-only, broad coverage). `@playwright/test`
— free/OSS, TypeScript-native, same ecosystem as the webui/vitest.

**Relationship to the existing pytest smoke:** Playwright is now the primary e2e. **Leave `backend/tests/smoke/`
in place** as an optional fast headless check — do **not** delete or rewire it. Where useful, **reuse its scenario
specs** (`backend/tests/smoke/scenarios/*.yaml`) as the single source of "what scenario / expected outcome" so the
two layers don't drift.

## Key setup facts (this repo)
- **webui is NOT in compose** — it's served separately (dev CORS). Playwright serves it via a `webServer` (build +
  `vite preview`, or `vite dev`) with `VITE_*_BASE` pointed at the **running compose backend** (the `.env` proxy
  bases already exist: `VITE_STUB_BASE`/`VITE_INGESTOR_BASE`/`VITE_RUNTIME_BASE`/`VITE_REGISTRY_BASE`/
  `VITE_GLEA_BASE`/`VITE_IDENTITY_BASE`/`VITE_NOTIFICATIONS_BASE`).
- **Auth = OIDC auth-code** via `webui/src/auth/oidc.ts` (issuer `…:8087/realms/amendia-dev`, client
  `amendia-webui`). Login is a redirect to the Keycloak page, then `AuthCallback`. Personas + `dev-password`:
  **priya** (process-owner/supervisor), **marcus** (ops-approver), **riya** (analyst). This flow is automated once
  per persona and cached (`storageState`).
- Nav/screens: **Dashboard, Task inbox, Instances, Cohorts (Instances/Definitions tabs), Triggers, Registry
  (onboarding wizard), Administration**.
- The condition-normalization banner + guided gateway fix (just shipped) live on the **Registry → onboarding
  wizard** (upload step + Gateways step). The DAG/SLA editor + inline edit live on a **Cohort definition** detail
  (owner-gated). Cohort SLA/breach board + badges on **Cohorts**. Instance diagram highlighting on **Instances**.

## Read first
- `tools/demo_wire_repair.sh` + `backend/tests/smoke/` (`drivers.py`, `scenarios/*.yaml`, `hitl.py`) — the
  scenario specs to reuse, the trigger drivers (pega_stub `POST /cases` / stub_generator), and the HITL
  gate/persona/artifact-output knowledge (which gates author artifacts — reuse the specs' `hitl.outputs`, now
  entered through the **UI form** instead of the API).
- `webui/src/auth/{oidc.ts,AuthCallback.tsx,SignIn.tsx}` + `app/RequireAuth.tsx` — the login flow to automate.
- `webui/src/features/cohorts/{CohortsPage,CohortDetailPage,CohortDefinitionPage}.tsx` — the cohort screens, the
  owner-gated inline edit + DAG/SLA editor, list badges, instance SLA panel.
- `webui/src/features/registry/OnboardingWizard.tsx` + the `conditionHardening.test.tsx` sibling — the wizard steps,
  the normalization banner, the per-gateway guided fix (what to assert in the UI on the §0-A publish journey).
- `backend/services/process-registry/app/routers/packs.py` (`POST /packs`, owner-gated) + `onboarding.py` — the
  deterministic load path (§0-B) and the wizard step endpoints; `GET /packs/{key}` to **capture** the committed
  manifest fixtures from a known-good stack.
- The Task Inbox feature (`webui/src/features/…` task inbox) — claim + decide + the artifact-authoring form for
  manual gates.
- `webui/vite.config.*` + `webui/.env` — the proxy wiring the `webServer` must reproduce.

## Deliverables

### 1. Harness (`webui/e2e/`, `@playwright/test`)
- **`playwright.config.ts`** — `baseURL` = the served webui; a `webServer` that builds+serves the webui with
  `VITE_*` pointed at the running compose backend (env-overridable); projects/`storageState` per persona; sane
  timeouts + retries; trace/screenshot on failure. The suite **loads its own packs** (see §0) — assume the compose
  stack is up; a **global preflight** skips the suite with a clear message only if the **backend is unreachable**
  (degrade-don't-error). It does **not** require packs to be pre-onboarded.
- **`global-setup.ts`** — (a) automate the OIDC login **once per persona** (priya/marcus/riya) through the Keycloak
  page and save `storageState`; tests attach the persona they need (no per-test re-login). (b) **deterministically
  load** the execution-scenario packs via `POST /packs` with committed manifest fixtures (see §0), idempotently
  (skip if already registered), so the HITL/cohort/SSE journeys have their packs without re-driving the wizard.

### 0. Onboarding & pack loading — two mechanisms (Sandeep: "Both")
This suite **tests onboarding as a journey AND is self-contained** (no pre-onboarded stack assumed):
- **A — full wizard → publish (real onboarding, under test):** one journey drives the **actual onboarding UI**
  end-to-end for a representative pack — upload the BPMN, step through capabilities/bindings/artifacts/triage/
  gateways, resolve the guided condition fix, and **Publish** — so the pack is loaded exactly as a user onboards
  it. Prefer a **Camunda `${…}`-authored** BPMN so this path also exercises the condition-normalization banner +
  guided gateway fix on the way to publish. **Determinism rule:** the copilot inference step is LLM-driven, so
  assert **stable outcomes** — pack appears in `GET /packs`, validation passed, the banner/guided-fix behaved,
  a deliberately-bad condition **blocks** "go live" — **not** exact inferred values; feed the human-authored
  decisions (bindings/gateway value) deterministically from a reference so the run is reproducible.
- **B — deterministic load (setup for the rest):** the other execution scenarios' packs are loaded in
  `global-setup` via `POST /packs` with **committed manifest fixtures** (`webui/e2e/fixtures/manifests/*.json`,
  captured from a known-good onboarded stack via `GET /packs/{key}`). This is deterministic + reproducible and
  **also exercises the onboarding-validation guard** (a bad manifest → 422), without paying the full-wizard cost
  per scenario.
- **Page objects / helpers** (`e2e/pages/*`, `e2e/support/*`) — Cohorts, CohortDefinition, OnboardingWizard,
  TaskInbox, Instances; a `fireScenario()` that reuses a spec's trigger driver over the API (the external
  orchestrator/stub is legitimately outside the webui) and returns the correlation value; a scenario loader for
  `backend/tests/smoke/scenarios/*.yaml`. **Prefer role/label/text selectors**; add a **minimal, bounded** set of
  `data-testid` attributes to webui components only where a stable hook is genuinely missing (non-behavioral).

### 2. Broad journey specs (`webui/e2e/tests/*.spec.ts`)
- **Cohorts render** — as priya, Cohorts → Instances shows a cohort with segments + state; the SLA/breach board +
  row badges render for a cohort that has SLA data; Definitions tab lists definitions.
- **Onboarding wizard → publish (the §0-A journey):** drive the **full** onboarding UI to **publish** a
  representative Camunda-`${…}` pack — upload → step through capabilities/bindings/artifacts/triage/gateways →
  the **normalization banner** (Camunda→FEEL, before/after) appears, the **Gateways step** shows the guided
  condition issue (field-less / unquoted) with a suggestion, applying it lets you proceed while an unresolved one
  **blocks** "go live" → **Publish** → assert the pack is **registered** (`GET /packs`) and validation passed.
  This both proves the hardening and **loads a real pack** (populates the registry). Assert stable outcomes, not
  LLM-inferred values (per §0-A).
- **Owner-gating** — the same cohort definition detail: **priya** sees the inline-edit + DAG/SLA editor; **marcus**
  sees **read-only** (no editor). Assert both (persona storageState).
- **DAG/SLA editor (forward-only)** — as priya, edit a definition: add a node/edge + an SLA, **Save**; the
  forward-only warning shows; the read view reflects the change; an obviously invalid graph surfaces the server
  message inline.
- **HITL via the UI (the arc)** — `fireScenario(ach happy path)` → **Task Inbox**: as the gate's persona, **claim
  and decide each gate through the UI**, filling the artifact form for the manual gates (from the spec's
  `hitl.outputs`); drive to terminal. Assert the **Instance** reaches `completed` and the **cohort closes**
  (`Released`) — read from the screens, not the API.
- **Live SSE** — after firing, **without reloading**, assert the cohort/instance row updates live (state/badge
  transitions) — the SSE-signal→refetch path only a browser can prove. Use `expect.poll`/auto-wait, no fixed sleeps.
- **Instance diagram highlighting** — open a terminal instance; the diagram renders and highlights the terminal
  node/path (ADR-062).

### 3. Launcher, deps, docs
- **`npm run e2e`** (= `playwright test`) + **`tools/e2e.sh`** — check the stack is reachable, build/serve the
  webui, run, print a per-journey PASS/FAIL summary, non-zero on failure; pass-through args (`-g`, `--project`).
- **Deps** — add `@playwright/test` as a devDependency; document `npx playwright install` (browsers). All free/OSS.
- **`webui/e2e/README.md`** — how to launch (compose up + onboard packs → `tools/e2e.sh`), the persona/storageState
  model, env overrides, adding a journey, and the **known trade-off** (browser e2e is slower/flakier than the
  pytest smoke — keep that as the fast check).

## Do not
- Do not delete or rewire `backend/tests/smoke/` — it stays as the optional fast layer; reuse its scenario specs.
- Do not re-assert pure backend logic that already has API/unit coverage — assert **UI** behavior (rendering,
  gating, forms, live updates). The browser suite earns its cost on the screens, not on re-checking the engine.
- Keep webui source changes to a **minimal, non-behavioral** set of `data-testid` hooks; no feature/logic changes,
  no ungating, no auth weakening. Prefer role/text selectors first.
- No fixed `sleep`s — use Playwright auto-wait / `expect.poll`. No paid tooling.
- Do not assert on the copilot's **LLM-inferred exact values** in the wizard journey — assert stable outcomes
  (published, validated, banner/guided-fix behaved, bad-condition blocks) so LLM variance can't spuriously red the
  suite. Feed human-authored decisions deterministically.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance
- With the compose stack **up** (packs **loaded by the suite**, not pre-onboarded), `bash tools/e2e.sh` (or
  `npm run e2e`) runs the broad suite green: the **full wizard journey publishes** a Camunda-`${…}` pack (appears
  in `GET /packs`, validation passed, banner + guided-fix shown, a bad condition **blocks** go-live); the
  deterministic `POST /packs` load registers the execution-scenario packs (and a bad manifest → **422** asserted);
  then login (priya/marcus), Cohorts render, owner-gating (priya editor / marcus read-only), DAG/SLA edit+save,
  **HITL driven entirely through the Task Inbox UI to a `completed` instance + `Released` cohort**, live-SSE row
  update, and instance diagram highlight.
- Backend **down** → the suite **skips** with a clear message (no confusing red). Re-runs are idempotent (pack
  load skips if already registered; the wizard journey targets a distinct pack_key/version so it can re-publish).
- Determinism: reruns are stable (auto-wait, storageState reused, traces on failure). A journey for a not-onboarded
  domain skips rather than fails.
- `@playwright/test` only; the existing pytest smoke still runs unchanged; webui `tsc`/`vitest`/build stay green.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_playwright_e2e_report.md` (uncommitted): (1) outcome
one-liner; (2) harness layout (config + `webServer`, global-setup OIDC login per persona + deterministic pack load,
page objects, scenario reuse); (3) **the two onboarding mechanisms** — the full wizard→publish journey (what it
asserts, how LLM-variance is avoided) and the `POST /packs` deterministic load (+ where the committed manifest
fixtures live and how they were captured); (4) the other journeys + what each asserts (HITL-via-UI, live SSE,
owner-gating, DAG/SLA edit); (5) any `data-testid` hooks added (list them — prove minimal/non-behavioral);
(6) launcher + deps + `playwright install`; (7) verification — exact command + the green run against your stack
(per-journey, incl. the wizard publish + the deterministic load), the stack-down skip; (8) follow-ups
(trigger-via-Triggers-UI, branch/SLA-breach journeys, CI wiring, test-data cleanup/correlation-prefix — same
pollution note as the pytest smoke). One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `webui/e2e/` + `tools/e2e.sh` + a minimal set of webui
`data-testid` hooks only; reuse the pytest scenario specs + the demo's persona/gate knowledge. Broad journeys,
HITL-and-everything-through-the-UI, live-SSE proven, degrading (skip, don't error), Playwright-only as the primary
e2e with the pytest smoke kept as the fast fallback.
