# ADR-062 — Precise process-diagram highlighting for terminal instances: report

## 1. Outcome

**Done.** A terminal (completed/failed/cancelled) instance's BPMN diagram and the context-rail step tracker now
green **only the elements the instance actually executed** (from `actor_log`); un-taken branches stay grey
(`pending`). Verified against a real `End_Resolved` wire instance — its `actor_log` is exactly the executed path
and nothing else, so no `actor_log`-broadening was needed. `tsc` clean; webui tests **175 passed** (+2).

## 2. The `deriveSteps` change + the `terminal` param

`webui/src/lib/steps.ts::deriveSteps`: **removed the blanket `else if (terminal) state = "done"` fallback**, so
`done` derives purely from `actor_log` membership (`failed`/`current` unchanged). The `terminal` option was
**removed** from `deriveSteps`' signature/destructuring (it existed only to drive that fallback).

Plumbing:
- `features/task/useProcessProgress.ts` — removed the `terminal` computation and stopped passing it (it was used
  *only* for `deriveSteps`).
- `features/instances/InstanceDetailPage.tsx` — stopped passing `terminal` to `deriveSteps`, but **kept** the
  `terminal` local: it still drives the duration display (`terminal ? updated_at : undefined`) and the `live`
  polling flag. So no dead param anywhere.

## 3. `actor_log`-completeness verification (the ADR-062 guard)

Confirmed against a **real completed instance** on the live stack — `pi-036f3d1ebab54936`, pack `wire-stan`,
`status=completed`, `outcome=End_Resolved` — fetched exactly as the webui does (`GET /instances/{id}`). Its
`actor_log` element_ids (deduped) are:

> **`Enrich, Assess, DraftRepair, ApproveRepair, Screen, ApplyRepair, Notify, Record`**

— precisely the executed wire happy path — and the un-taken branches **`DraftReturn, ApproveReturn,
ExecuteReturn, ObtainInfo, Escalate`** are **absent**. (`ApplyRepair`/`Notify` appear twice — the
`approve_actions` propose-then-execute pair — but `deriveSteps` uses a `Set`, so that's just `done` either way.)
`artifact_names` corroborate (`screening`, `resolution_record`, `notification`, `repair_result`, …).

So `deriveSteps(pack.bindings, actor_log)` greens exactly the executed path and greys everything else — the
intended behaviour — and **every genuinely-executed task is present in `actor_log`**. The committed-artifact
broadening (Task 2's fallback) was therefore **not** required. (The pack itself was later deleted by ADR-061, so
the browser diagram can't be rendered against this instance now, but the diagram is a pure function of
`deriveSteps(bindings, actor_log)`, and the `actor_log` — its only `done` input — is verified complete.)

## 4. Tests updated

`webui/src/features/task/contextRailSteps.test.ts`:
- Removed `terminal: true` from the failed-instance test (it now type-errors — and `Task_A` is `done` via
  `actor_log` regardless).
- Added an ADR-062 block over a 3-binding branching pack:
  - a **COMPLETED** instance (`actor_log = [A, B]`) → `A` done, `B` done, **`C` pending** (asserts `C` is *not*
    greened just because the instance is terminal).
  - a **FAILED** instance (`failedElementId = B`) → `A` done, `B` failed, `C` pending (failed node red, path
    green, rest grey).

`processDiagram.test.tsx` needed no change: `ProcessDiagramView` emits a marker per step regardless of state, so
its `markers:1` count assertion is unaffected; `BpmnViewer` already renders `pending` grey (running instances
use it). The context rail uses the same `deriveSteps`, so it inherits the precise semantics automatically.

## 5. Verification

- `npx tsc --noEmit` → **exit 0**.
- `npx vitest run` → **27 files / 175 tests passed** (was 173; +2 ADR-062 tests). Touched suites
  (`contextRailSteps`, `processDiagram`) green.
- Live: `GET /instances/pi-036f3d1ebab54936` → the `actor_log` set above (executed-path-only), confirming the guard.
- During-execution behaviour unchanged: `current` (open/claimed gate → purple) and `failed` logic are untouched;
  only the terminal all-green fallback was removed.

## 6. Left open

- Nothing functional. The only caveat is that the specific verification instance's pack (`wire-stan`) was
  deleted by the earlier ADR-061 work, so a *browser* screenshot against that exact instance isn't renderable
  now; the `actor_log` data (the sole driver of `done`) is verified complete via the runtime API, which is
  equivalent. A fresh onboard + happy-path run would render it end-to-end in the UI if a visual check is wanted.
