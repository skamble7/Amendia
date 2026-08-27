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
bash tools/e2e.sh              # THE CI GATE — all deterministic journeys, per-journey summary; onboard → run → teardown
bash tools/e2e.sh -g owner     # pass-through Playwright args (-g grep, --project chromium, …)

bash tools/e2e-copilot.sh      # NON-BLOCKING copilot/LLM lifecycle — real autopilot onboard; RETAINS everything; skips w/o a model
```

**Two commands, no flags.** `tools/e2e.sh` is the **reliable gate**: deterministic (rule-based `infer_draft`, no
LLM), fast, and it tears down. `tools/e2e-copilot.sh` is a **separate, non-blocking** command that proves the
**real copilot onboarding path** end-to-end (onboard the 3 ACH segments via the LLM autopilot → form the cohort →
run the 3 pega flows) and **retains everything** for inspection; it **skips** cleanly when the stack has no copilot
model, and it **never gates CI**. It needs the copilot model + a **clean DB** on each run (it retains, so a re-run
must start from `down -v`). See `ach-copilot-lifecycle.spec.ts` and
[the running-e2e doc](../backend/docs/engineering/running-e2e-tests.md#the-copilot-lifecycle-command-tools-e2e-copilotsh).

> **This is a top-level, full-system suite** (`e2e/` at the repo root) — frontend + backend + stubs + DB — with its
> own `package.json` / `node_modules`. It is not part of the webui package; nothing here imports webui `src`. The
> only cross-boundary tie is the `webServer`, which serves the webui via `vite dev` from `../webui`.

**Self-contained — no manual "onboard ACH first" step.** `global-setup.ts` runs the deterministic, copilot-free
driver (`fixtures/onboarding/onboard_ach.py`) that onboards the three ACH packs to active, creates the
`ach_exposure_cohort` definition, and grants the `role.ach_*` gate roles across two humans (marcus/riya, via the
identity admin API, as an operator would after publishing). `global-teardown.ts` always revokes the roles and
ADR-061 clean-deletes the packs + definition. Idempotent; safe from an empty, minimally-seeded registry. See
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
- **ach-lifecycle** (flagship) — the full ach_exposure acceptance narrative, FAITHFUL to the BPMNs + Amendia's rule
  that any side-effectful activity is human-gated: priya onboards the 3 segments (every side-effectful action tool
  `approve_actions`-gated — A's `notify_pega` handback, B's prepare/request_purge/notify, C's mark/purge/notify —
  plus the AuthorizeRelease/Purge + ReviewArtifacts decisions) and owns the cohort, then steps out. Access is split
  to **two distinct humans** (Marcus → enforce/B, Riya → assess/A + closeout/C); the runtime AND UI enforce
  role-holding at claim. Every gate is driven through the Task Inbox as its role-holder, and each flow asserts the
  cohort reaches **MEMBERS = 3** (assess+enforce+closeout all joined & terminal) and closes — a **1-member stall
  fails**. Flows: **credit_approve** → 3 members/Released, **debit_reject** → purge branch/3 members/Purged,
  **late_closeout** → enforce→closeout SLA **breaches (owner=external)** on the SLA board, 3 members, still Released.
  (No manifest SoD — with actions gated, an intra-enforce `distinct_actor` would stall the single approver; SoD is
  cross-segment, honoured by the exclusive role split.)
- **hitl-arc** — fire ACH → resolve each gate **in the Task Inbox** (claim + author the manual gates' artifacts via
  the raw-JSON form) → the **cohort closes Released**, asserted off the Cohorts screen.
- **live-sse** — with Cohorts open and **not** reloaded, a fired case's row appears live (SSE → refetch).
- **instance-diagram** — a terminal instance renders its highlighted BPMN diagram (ADR-062).

## The copilot lifecycle command (separate, non-blocking — `tools/e2e-copilot.sh`)

`e2e/tests/ach-copilot-lifecycle.spec.ts` (its own `playwright.copilot.config.ts`, **not** part of the gate above)
drives the **real copilot autopilot** to onboard the 3 ACH segments (`/registry/onboard`: upload BPMN → point at the
segment MCP → author trigger schema + triage → Generate → **accept as-is** → publish; fresh pack keys per run),
then runs the **same ach_exposure lifecycle** the gate proves — cohort formation, role-gated HITL, DAG+SLA, and the
3 pega flows — but over **copilot-inferred** packs. Because inference varies per run, **everything is read from the
live packs** and nothing inferred is asserted or hardcoded: each **manual gate's value is synthesized from its
inferred artifact schema** (`support/copilot.ts` — the fix for the de-risk's 422), and because the copilot often
infers a **4-eyes `distinct_actor` SoD within enforce** that a single approver can't satisfy, **every gate role is
granted to both marcus and riya** and each gate is driven by the **SoD-aware picker** (marcus primary; riya provides
the second signature). It **retains everything** (no teardown), and **skips** cleanly when the stack has no copilot
model (502 `copilot_llm_unavailable`). A produced-but-unpublishable draft, or a cohort that stalls below 3 members,
is a real failure. Non-blocking by design — it never gates CI. Re-run needs a clean DB (`down -v`), since it retains.

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
