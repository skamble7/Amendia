# Claude Code prompt — Playwright e2e follow-up: **real onboarding journey + self-contained from an empty seed**

Two gaps to close in the existing Playwright suite (`webui/e2e/`), found on a fresh-DB run (4 passed / 6 skipped /
1 failed):
1. **There is no real onboarding test** — `onboarding-condition.spec.ts` only asserts the normalization *banner*;
   it never drives the wizard to **publish** a pack. Add a genuine onboarding journey.
2. **The suite is not self-contained** — `backend.ts` only *checks* whether the ACH packs are onboarded and skips
   the ACH journeys otherwise; nothing loads them and nothing creates the `ach_exposure_cohort` definition. So on an
   empty DB every ACH journey skips, and the un-guarded `cohorts` test **fails**. Make the suite **onboard/create
   what it needs, then execute**, starting from an empty minimally-seeded DB.

**Operating assumption (Sandeep guarantees it):** each run starts from an **empty, minimally-seeded** stack — no
packs, no cohort definitions, no instances — but with everything onboarding+execution *needs* already up:
identity personas (priya=`role.process.owner`+`platform.admin`, marcus=ops-approver, riya=ops-analyst), the
Keycloak realm/users, and the five `mcp_stub` capability servers (`ach_exposure_assess`, `ach_decision_enforce`,
`ach_closeout`, `restaurant_dinein`, `wire_transfer_exception`). Document this contract; the suite must **not**
assume any pack/definition pre-exists.

## Read first
- `webui/e2e/support/backend.ts` (the check-only `activePackKeys`/`missingPacks` — replace the "skip if missing"
  posture with "load if missing"), `global-setup.ts`, `support/fixtures.ts`, `support/scenarios.ts`, `fixtures/`.
- `webui/e2e/tests/{onboarding-condition,cohorts,hitl-arc,owner-gating,dag-sla-editor}.spec.ts` — the journeys to
  extend/fix.
- `backend/services/process-registry/app/routers/packs.py` (`POST /packs`, owner-gated) and `onboarding.py` (the
  wizard step endpoints incl. `copilot/generate`, `capabilities`, `bindings`, `artifacts`, `triage`, `policies`,
  `assemble`, `commit`) — the onboarding surface. Note: a raw `POST /packs` manifest references
  `cap.…`/`art.…` that must already be **registered**; on an empty DB those come from onboarding (MCP introspection
  + artifact registration), so the deterministic setup must register the dependencies too (see §2's wrinkle).
- `backend/services/process-registry/app/routers/cohort.py` — `POST /cohort/definitions` (owner-gated) to create
  `ach_exposure_cohort`; the ADR-063/064 cohort definition + expectation-graph/SLA shape.
- `backend/docs/methodology/worked-examples/ach_exposure/ONBOARDING.md` + the three ACH `.bpmn` + the ACH manifest
  (the pack manifest for `exposure`/`enforce`/`closeout`) — the source for the deterministic fixtures and the
  cohort definition.
- ADR-061 (clean pack deletion) — for teardown.

## Deliverables

### 1. A real onboarding journey (the coverage) — `onboarding.spec.ts`
Drive the **full wizard to Publish** for one representative pack (prefer the Camunda-`${…}` BPMN already in
`fixtures/camunda-gateways.bpmn`, so this also covers the hardening on the way): upload → step through
capabilities/artifacts/bindings/triage/**gateways** (the normalization banner + guided condition fix appear;
applying it proceeds, an unresolved bad condition **blocks** "go live") → **Publish** → assert the pack is
**registered** (`GET /packs`) and validation passed. Owner-gating: only **priya** can publish; a non-owner can't.
**Determinism rule:** the copilot inference is LLM-driven — assert **stable outcomes** (published, validated,
banner/guided-fix behaved, bad-condition blocks, owner-gated), **never** exact inferred values; feed the
human-authored decisions deterministically. This is the "we test onboarding" journey; it need not be executed.

### 2. Self-contained execution setup from empty (`global-setup.ts` + `backend.ts`)
Before the execution journeys, **ensure the ACH domain exists** (idempotent — create only if absent):
- **Onboard the three ACH packs deterministically** (no copilot/LLM in the setup path — setup must be reliable).
  **Wrinkle to handle:** on an empty DB the packs' capabilities + artifact schemas aren't registered yet, so a bare
  `POST /packs` will 422. Pick a deterministic mechanism and document it: either (a) **replay a captured onboarding**
  — the exact non-copilot onboarding API call sequence (introspect capabilities from the running `mcp_stub` →
  register artifact schemas → `assemble` → `commit`) with fixed request bodies captured from a known-good run and
  committed under `webui/e2e/fixtures/onboarding/`; or (b) register the capability/artifact dependencies then
  `POST /packs` the committed manifests. Capture the fixtures once from an onboarded stack (`GET /packs/{key}` +
  the onboarding bodies); commit them.
- **Create the `ach_exposure_cohort` cohort definition** via `POST /cohort/definitions` (priya token) — including
  its expectation-graph/SLA if the SLA journeys need it — so the Definitions tab, cohorts, and HITL/cohort journeys
  have it.
- Replace `backend.ts`'s **skip-if-missing** with **load-if-missing** (the check stays only as a final guard:
  if load genuinely failed, skip with a clear reason rather than a confusing red).

### 3. Fix the cohorts test robustness (`cohorts.spec.ts`)
The `Instances/Definitions` test must **skip** (like its sibling) when there's no cohort definition/instance, not
hard-fail on `getByText("ach_exposure_cohort")`. After §2 it will normally find the definition; the guard prevents
a confusing red if setup is skipped (e.g. stack down).

### 4. Teardown — leave the stack as found (`global-teardown.ts`)
Remove **only the run's own** data so repeated runs don't accumulate (esp. ClickHouse cohort rows): clean-delete the
wizard-published pack + the deterministically-loaded ACH packs via **ADR-061**, delete the `ach_exposure_cohort`
definition, and delete the run's fired cases/cohorts (tag them with a **run-scoped correlation prefix**, e.g.
`e2e-<runId>-…`, and delete by prefix). Idempotent; never touch data it didn't create. (Sandeep resets the DB per
run, but teardown keeps a single session clean and supports back-to-back runs.)

### 5. Docs — the minimal-seed contract
Update `backend/docs/engineering/running-e2e-tests.md` + `webui/e2e/README.md`: what the **minimal seed must
provide** (identity personas, Keycloak realm/users, the five `mcp_stub` servers up; empty registry) vs. what the
**suite creates** (onboards ACH, creates the cohort definition, publishes the wizard pack) and tears down. Remove
the old "onboard ACH first" manual prerequisite — the suite now does it.

## Do not
- Do not put the **copilot/LLM** path in the *setup* (§2) — setup must be deterministic/reliable. The LLM wizard is
  only the §1 *coverage* journey, and there only stable outcomes are asserted.
- Do not assume any pack/definition pre-exists; do not leave the ACH journeys skipping on an empty seed. Do not
  weaken owner-gating. Keep webui source changes to a minimal, non-behavioral set (prefer existing ARIA/roles).
- No fixed sleeps (auto-wait/`expect.poll`). No git writes — leave the tree dirty.

## Acceptance
- From an **empty, minimally-seeded** stack (`docker compose … down -v` → `up` → mcp_stub up), with **no manual
  onboarding**, `bash tools/e2e.sh` runs **green**: the onboarding journey publishes + validates a pack (banner +
  guided-fix + bad-condition-blocks + owner-gated); setup deterministically onboards the three ACH packs and creates
  `ach_exposure_cohort`; then HITL-arc drives gates in the UI to a `completed` instance + **cohort closed/Released**,
  cohorts render (Definitions lists `ach_exposure_cohort`), owner-gating (priya editor / marcus read-only), DAG/SLA
  edit, live-SSE, and instance-diagram all pass. **No ACH journey skips for missing data.**
- Re-runs are idempotent (setup creates-only-if-absent; teardown removes only the run's data → back-to-back
  `tools/e2e.sh` both green). Stack genuinely down → clean skip. The `cohorts` test **skips** (not fails) if setup
  didn't run.
- The setup path uses **no copilot/LLM**; the onboarding journey asserts stable outcomes only. Existing pytest smoke
  untouched; webui `tsc`/`vitest`/`build` stay green.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_playwright_onboarding_selfcontained_report.md` (uncommitted):
(1) outcome one-liner; (2) the onboarding journey (what it drives + the stable-outcome assertions + how LLM variance
is avoided); (3) the deterministic setup — which mechanism (replay vs register+POST), where the fixtures live, how
the capability/artifact dependency wrinkle was solved, and the cohort-definition creation; (4) the cohorts skip-fix;
(5) the teardown (ADR-061 delete + run-scoped correlation cleanup); (6) the documented minimal-seed contract;
(7) verification — exact commands + a green run **from `down -v`** (per journey, no skips), a back-to-back re-run,
and the stack-down skip; (8) follow-ups. One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `webui/e2e/` + `tools/` + docs only. Deterministic,
copilot-free setup; a real (stable-outcome) onboarding journey; self-contained from an empty minimal seed;
degrade-don't-error; teardown leaves the stack as found. This makes `tools/e2e.sh` green from a clean `down -v`
with zero manual onboarding — onboarding itself under test.
