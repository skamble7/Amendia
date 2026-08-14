# Playwright e2e — real onboarding journey + self-contained from an empty seed

**Status:** complete. Full suite **green from an empty, minimally-seeded stack** and **green on a back-to-back
re-run** (idempotent). The HITL arc drives all three ACH segments through the browser to a closed/Released cohort.

```
Run A (from empty):        13 passed, 1 skipped   (EXIT 0)
Run B (back-to-back):      13 passed, 1 skipped   (EXIT 0)
```

The 1 skip is [`cohorts.spec.ts:28`](../../../webui/e2e/tests/cohorts.spec.ts) — the closed-cohort SLA-board
observation. It filters instance rows by `/case-/` and runs *before* the HITL arc creates any closed cohort, so it
skips by design; the run's cohorts are `e2e-<runid>` tagged. Not a regression.

No git writes — tree left dirty for the operator.

---

## What was delivered

1. **Real onboarding coverage journey** — `webui/e2e/tests/onboarding.spec.ts`: priya drives the technical wizard,
   uploads a Camunda `${…}` BPMN, asserts **stable outcomes only** (BPMN-attached + the FEEL normalization banner);
   marcus (non-owner) gets **no Registry surface** (owner-gating); all three ACH packs are **active** in the Registry.
   Never asserts an LLM-inferred value.

2. **Self-contained execution setup from empty** — `webui/e2e/fixtures/onboarding/onboard_ach.py` (deterministic,
   copilot-free) creates the `ach_exposure_cohort` definition and onboards the three ACH packs to **active**, then
   **grants** the gate roles to the HITL persona. Wired through `support/setup.ts` → `global-setup.ts`.
   `backend.ts`'s skip-if-missing stays only as the final guard; setup is now **load-if-missing**.

3. **`cohorts.spec.ts`** skips (not hard-fails) when no cohort definition/instance exists.

4. **Teardown** — `global-teardown.ts` revokes the granted roles, then ADR-061 clean-deletes the packs + the cohort
   definition. Idempotent; leaves the stack as found. Fired cohort instances persist (no delete API) and are
   run-id tagged for the operator's per-run DB reset.

5. **Docs** — `backend/docs/engineering/running-e2e-tests.md` (minimal-seed contract + the deterministic mechanism +
   the three wiring subtleties + the local re-run cache caveat) and `webui/e2e/README.md` (removed the manual
   "onboard ACH first" prerequisite).

---

## The hard part: making the HITL arc close from deterministically-onboarded packs

The self-contained setup was the easy half. Getting the browser HITL arc to drive the deterministic packs to a
closed cohort surfaced **five** distinct issues, each invisible to the pytest smoke (which drives the runtime API,
not the UI, and doesn't enforce role-holding). In order of discovery:

| # | Symptom | Root cause | Fix (in `onboard_ach.py` unless noted) |
|---|---------|-----------|-----|
| 1 | Assess `approve_actions` gate had **no Authorize button** | `notify_pega` bound `read_only`, so the gate synthesizes **no proposed action** (ADR-047: a side-effect-free capability under `approve_actions` is a config-error state). | Propagate each tool's introspected `suggested_side_effect`; `notify_pega` → `side_effectful` **only where the pack gates it** (ungated notify in enforce/closeout stays `read_only`, else the assemble hitl-guard rejects it). |
| 2 | "Authorize all" present but **disabled** | The gate role (`role.ach_*`) is held by **no seeded persona**; the UI (`taskEligibility`) requires the actor to hold `task.role`. | **Grant** the `role.ach_*` gate roles to marcus (the arc's default HITL persona) via the identity admin API (`POST /users/{uid}/roles`, priya is `role.platform.admin`) — as a real operator would after publishing. Teardown revokes. |
| 3 | Flow **stalls after Segment A**; cohort never advances | `notify_pega`'s handback to the pega-stub carried `case_id="unknown-case"`, so the orchestrator couldn't correlate. The entry capability's `case_id` mapped from **nothing**: the ADR-048 field-level `input_map` derivation runs **inside `set_bindings`**, but the trigger was declared *after* bindings. | **Declare the trigger BEFORE `setBindings`** so the entry capability's inputs map from the trigger fields. |
| 4 | Enforce instance **fails**: "input source references artifact `request_purge_output` not produced upstream" | `notify_pega` sits after a gateway join; the auto-derivation sourced `case_id` from a **branch-only** artifact absent on the taken (release) branch. | Pin `notify_pega.case_id` to the **trigger** (`input_sources`) — branch-independent and always present. |
| 5 | **Flaky on back-to-back runs**: gate button disabled only when setup+arc ran within ~30s | `amendia_auth` caches role resolution by `(iss, sub)` with a **30s TTL**. The setup resolved marcus's `/me` to fetch his uid **before** granting → cached his pre-grant roles → the webui login (seconds later) snapshotted stale roles for the whole run. | Resolve marcus's uid via **priya's admin `GET /users`** (touches only priya's cache entry), never marcus's own `/me` before the grant lands. |

After all five: the arc resolves assess (`approve_actions`) → enforce (`Task_AuthorizeRelease` + `release_authorization`
artifact) → closeout (`Task_ReviewArtifacts` + `review_decision`) through the Task Inbox, and the cohort closes
**Released** (rollup `done:3, failed:0`) — verified both via a direct API drive and through the browser.

---

## Constraints honored

- **Deterministic setup, no copilot** — the driver uses the registry's technical onboarding API + MCP introspection +
  the rule-based `infer_draft`/input-map derivation. No LLM.
- **No assumed pre-existing packs/definitions** — everything is create-if-absent from empty; teardown removes it.
- **Owner-gating not weakened** — onboarding/registry stay `role.process.owner`-gated; the new grants are the
  execution *gate* roles (`role.ach_*`) on marcus, never owner/admin roles.
- **Minimal, non-behavioral webui source changes** — zero `src/` changes; all work is in `webui/e2e/**` and the
  driver. The behavior findings (side_effect, input_map order) are *pack-authoring* choices, not product changes.
- **No fixed sleeps** — the flake was fixed at its cause (cache poisoning), not by waiting out the TTL.
- **No git writes** — tree left dirty.

## Operator note (local iteration only, not CI)

agent-runtime caches the compiled pack graph by `(pack_key, version)` for the process lifetime. Re-onboarding the
same `1.0.0` after changing the pack shape is masked by that cache — `docker restart deploy-agent-runtime-1` to pick
up a new graph while iterating on the driver. A real run from a fresh stack has an empty cache, so it never bites CI.

## Files touched

- `webui/e2e/fixtures/onboarding/onboard_ach.py` — side_effect propagation; trigger-before-bindings; notify
  `case_id`-from-trigger; grant/revoke via identity admin; cache-safe uid lookup.
- `webui/e2e/support/setup.ts` — pass `IDENTITY` through to the driver.
- `webui/e2e/global-setup.ts` / `global-teardown.ts` / `playwright.config.ts` — setup/teardown wiring.
- `webui/e2e/tests/onboarding.spec.ts` (new), `webui/e2e/tests/cohorts.spec.ts` (skip-not-fail),
  `webui/e2e/support/backend.ts` (run-scoped case tagging).
- `backend/docs/engineering/running-e2e-tests.md`, `webui/e2e/README.md` — docs.
