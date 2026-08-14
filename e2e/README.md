# Playwright UI e2e — the primary end-to-end suite

Drives the real **webui → backend** stack as a user: logs in through Keycloak, renders the cohort/instance
screens, exercises the onboarding wizard (condition-normalization banner), owner-gating and the DAG/SLA editor,
resolves HITL gates **entirely through the Task Inbox UI**, and proves **live SSE** updates. `@playwright/test`
only (free/OSS, TS-native). The pytest smoke (`backend/tests/smoke/`) stays as the **fast headless** check — this
browser suite is the broad, slower primary e2e; both reuse the same scenario specs so they don't drift.

## Launch

```bash
docker compose -f backend/deploy/docker-compose.yml up -d      # empty, minimally-seeded stack — NO packs needed
docker compose -f pega_stub/deploy/docker-compose.yml up -d    # ACH's mock Pega orchestrator (HITL journey)

(cd e2e && npm install && npx playwright install chromium)     # one-time: deps + browser (installed under e2e/)

# run from the repo root:
bash tools/e2e.sh              # all journeys, per-journey PASS/FAIL summary
bash tools/e2e.sh --keep       # keep the onboarded stack (skip teardown) — reuse it in the UI / next run
bash tools/e2e.sh -g owner     # pass-through Playwright args (-g grep, --project chromium, …)
# or, from e2e/: npm run e2e
```

> **This is a top-level, full-system suite** (`e2e/` at the repo root) — frontend + backend + stubs + DB — with its
> own `package.json` / `node_modules`. It is not part of the webui package; nothing here imports webui `src`. The
> only cross-boundary tie is the `webServer`, which serves the webui via `vite dev` from `../webui`.

**Self-contained — no manual "onboard ACH first" step.** `global-setup.ts` runs the deterministic, copilot-free
driver (`fixtures/onboarding/onboard_ach.py`) that onboards the three ACH packs to active, creates the
`ach_exposure_cohort` definition, and grants the `role.ach_*` gate roles to **marcus** (via the identity admin API,
as an operator would after publishing). `global-teardown.ts` revokes the roles and ADR-061 clean-deletes the packs +
definition — **unless `E2E_KEEP` (or `tools/e2e.sh --keep`) is set**, which skips teardown so the onboarded stack
stays usable (setup is create-if-absent, so the next run reuses it; data then accumulates until a normal run or a
`down -v`). Idempotent; safe from an empty, minimally-seeded registry. See
[backend/docs/engineering/running-e2e-tests.md](../backend/docs/engineering/running-e2e-tests.md) for the
minimal-seed contract and the three subtle wiring details the HITL arc depends on.

Playwright serves the webui itself (a `webServer` running `vite dev`, whose proxy sends `/api/*` to the compose
backend via `VITE_*_URL` — already the `18xxx` defaults). `global-setup.ts` logs **priya / marcus / riya** in once
through Keycloak and snapshots each persona's auth; specs pick one with `test.use({ persona })`.

## What the journeys assert

- **cohorts** — Instances tab lists cohorts with state; Definitions tab lists definitions; the SLA board renders
  when a cohort has SLA data.
- **onboarding-condition** — uploading a Camunda `${…}` BPMN surfaces the normalization banner ("Converted N …
  from Camunda", before/after).
- **owner-gating** — priya sees the definition editor; marcus sees it read-only (two persona projects, one screen).
- **dag-sla-editor** — build + Save a graph on a throwaway definition (invalid graph → the server 422 inline;
  valid → read view reflects it); the real ACH definition shows the forward-only warning on Edit.
- **hitl-arc** — fire ACH → resolve each gate **in the Task Inbox** (claim + author the manual gates' artifacts via
  the raw-JSON form) → the **cohort closes Released**, asserted off the Cohorts screen.
- **live-sse** — with Cohorts open and **not** reloaded, a fired case's row appears live (SSE → refetch).
- **instance-diagram** — a terminal instance renders its highlighted BPMN diagram (ADR-062).

## Persona / storageState model

react-oidc keeps tokens in **sessionStorage** (which Playwright's `storageState` does not capture), so
`global-setup` snapshots each persona's `sessionStorage` to `e2e/.auth/<persona>.session.json` and the `page`
fixture re-injects it via `addInitScript` before the first navigation (cookies ride the normal `storageState`).

## Degrading (skip, don't error)

`global-setup` writes `e2e/.auth/preflight.json`. Backend/webui **down** → every test skips with the reason. If the
deterministic setup can't complete, the ACH **execution** journeys skip ("ACH setup incomplete") and `cohorts` skips
when no definition is present — never a hard fail. Only a stack that's up + onboarded but produces the wrong UI state
is a failure.

## Env overrides

`E2E_BASE_URL` (`:5173`), `INGESTOR`/`RUNTIME`/`REGISTRY`/`GLEA`/`STUB`/`PEGA_STUB`/`IDENTITY`/`NOTIFICATION`
(compose host ports), `KEYCLOAK` (`:8087`), `REALM`, `CLI_CLIENT`/`CLI_SECRET`/`DEV_PASSWORD`. See `support/env.ts`.

## Add a journey

Drop `e2e/tests/<name>.spec.ts`, `import { test, expect } from "../support/fixtures"`, pick a persona with
`test.use({ persona })`, and reuse the page objects in `pages/screens.ts` + the scenario specs
(`support/scenarios.ts`, sourced from `backend/tests/smoke/scenarios/*.yaml`). Fire a trigger with
`fireScenario()` (the external orchestrator/stub is legitimately outside the browser); do everything else through
the UI.

## Known trade-off

Browser e2e is slower and flakier than the pytest smoke (a full HITL arc is ~1–3 min). Keep the pytest smoke as
the fast pre-flight; run this suite for broad, user-visible coverage. Traces/screenshots/video are retained on
failure under `e2e/.artifacts`; `npm run e2e:report` opens the HTML report.

## Known follow-ups

Fire via the **Triggers UI** (instead of the stub API); branch / SLA-breach journeys (ACH `late_closeout`);
CI wiring (ephemeral onboarded stack); test-data cleanup / a correlation prefix (same pollution note as the pytest
smoke — fired cases persist as closed cohorts).
