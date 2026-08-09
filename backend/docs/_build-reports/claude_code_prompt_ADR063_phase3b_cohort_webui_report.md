# ADR-063 Phase 3B — cohort webui (list, detail w/ member BPMN, backlink, new-cohort): report

**This completes ADR-063 Phase 3 — and the ADR end-to-end: runtime → close → read → UI.** Phase 3B is the
webui, coded against the landed Phase-3A endpoints. Backend untouched.

## 1. Outcome

The cohort UI is in: a **Cohorts list**, a **detail page whose hero is per-member BPMN diagrams with live
per-member execution highlighting**, a **cohort backlink banner** on the instance view, and a **New-cohort**
flow (register a definition + assign membership to active packs with a per-pack correlation-key picker). Reuses
the existing BpmnViewer + deriveSteps + instance-diagram path — no BPMN/step logic reinvented. `typecheck`,
`lint`, and the webui test suite are green.

## 2. Files added / reused

Added (all under `webui/src`):
- `api/services/cohorts.ts` — glea reads (`getCohorts`/`getCohort`/`getCohortByCorrelation`, `optional()`
  null-on-404/503) + registry writes/reads (`listCohortDefinitions`, `createCohortDefinition`,
  `assignMembership`, `clearMembership`, `getTriggerFields`, `listActivePacks`).
- `features/cohorts/queries.ts` — react-query hooks (`useCohorts`, `useCohort`, `useCohortByCorrelation`,
  `useCohortDefinitions`, `useActivePacks`, `useTriggerFields`).
- `features/cohorts/{CohortsPage,CohortDetailPage,NewCohortPage,MemberDiagram,CohortBacklink,cohortBits}.tsx`
  + `cohorts.test.tsx`.
- `api/types.ts` — hand-typed cohort read-models (`CohortListOut`, `CohortDetailOut`, roster/event/close,
  `CohortDefinition`) mirroring glea/registry, plus the three cohort fields on `InstanceDetail`.

Reused (not reinvented): `features/registry/BpmnViewer` (`BpmnMarker`), `lib/steps.deriveSteps`,
`features/instances/queries` (`usePack`, `useInstance`) + `features/registry/queries` (`usePackBpmn`) — the exact
instance-diagram path; the UI kit (`Card`/`Table`/`Badge`/`Button`/`Input`/`Textarea`/`Label`), `primitives`
(`EmptyState`/`LiveDot`/`IdMono`), `PageHeader`, `ConnectivityState`.

Touched: `router.tsx` (+4 routes), `app/AppShell.tsx` (+Cohorts nav), `features/instances/InstanceDetailPage.tsx`
(banner), `test/renderApp.tsx` (+cohort routes), `api/gen/registry.ts` (regenerated from the Phase-3A snapshot).

## 3. How the member diagrams fetch + derive state (the hero)

`MemberDiagram` (one per roster member) reuses the instance-view path exactly: `usePack(pack_key, pack_version)`
(manifest) + `usePackBpmn(...)` (diagram XML) + `useInstance(process_instance_id)` (its `actor_log`, `status`,
open HITL gate). It runs `deriveSteps(pack, actor_log, { currentElementId, failedElementId })` → `BpmnMarker[]` →
`BpmnViewer` — so a running member greens its executed path + shows the current node, un-taken branches stay
`pending`, a failed member reddens the failed node (ADR-062 precision, per member; no "terminal → all done").
Degrades gracefully: if a member's BPMN/instance is unavailable, the roster header still renders (a "diagram
unavailable" note instead of a crash). The header links to the full instance view. **Roster vs rollup respected:**
a `late: true` member renders with a "⚠ late join" badge and is counted in the roster but not in
`member_count`/`rollup` (so `roster.length` can exceed `member_count`).

## 4. Routing / nav

`router.tsx`: `cohorts` (list), `cohorts/new`, `cohorts/:cohortId` (detail), and
`cohorts/by-correlation/:correlationValue` (detail resolved by the business key — same page, `useParams`
switches the hook). `AppShell` gains a **Cohorts** nav item (Network icon) next to Instances, on the operator
surface. Existing routes untouched. The instance backlink links to `cohorts/{cohort_instance_id}`.

## 5. New-cohort flow

`NewCohortPage`: (a) **definition** — id, display name, description, the close JSON-Schema (textarea, live
JSON-parse validation), correlation + outcome dotpaths → `POST /cohort/definitions`; (b) **members** — active
packs (`listActivePacks`), each with an Add toggle and a **per-pack correlation-key selector populated from
`getTriggerFields(pack, version)`** (a free dotpath input when the pack declares no trigger fields); on save,
`PUT …/cohort-membership` per assigned pack. Validates id present, close schema parses, each assigned pack has a
key (blocks submit + inline error). "Manage membership" from the detail header opens the same flow.

## 6. Tests (`features/cohorts/cohorts.test.tsx`, 8 — MSW + renderApp, BpmnViewer mocked)

- **List:** rows + rollup counts + state chips (`Closing`/`Closed`) + late-join flag + outcome from a mocked
  `CohortListOut`; empty state when `count: 0`.
- **Detail:** roster → **one `BpmnViewer` per member** (`xml:loaded`), the late badge, `member_count` (1) ≠
  `roster.length` (2), the ordered event stream (`opened`/`member_joined`), and the close card; plus a
  not-found state on a 404.
- **New cohort:** Add a pack → its trigger fields populate the key `<select>`; submit calls
  `createCohortDefinition` **and** `assignMembership` per assigned pack (captured); invalid close JSON blocks
  submit (no API call, inline error).
- **Instance backlink:** banner renders with a working `/cohorts/{id}` link when `cohort_instance_id` is
  present, and is **absent** for a standalone instance.

## 7. Verification

- `npx tsc --noEmit` → **clean** (exit 0).
- `npx vitest run` → **28 files / 183 tests passed** (+8; prior suites unaffected).
- `npx eslint` on the new/touched files → **0 errors** (1 hooks-deps warning fixed).
- `gen:api` regenerated `src/api/gen/registry.ts` **offline from the committed Phase-3A snapshot**
  (`webui/openapi/registry.json`) so registry types carry the new cohort/trigger-fields routes.

## 8. Left open

- **`gen:api:check` needs the live stack.** It regenerates *every* service and only `registry` has an offline
  snapshot — `stub`/`ingestor`/`runtime`/`identity` require the compose stack up, so the full check must be run
  by the operator with the stack running (`docker compose … up`, then `npm run gen:api && git add src/api/gen`).
  I regenerated `gen/registry.ts` offline so registry won't show drift; the other services' `gen/*.ts` are
  unchanged. glea cohort types are **hand-written** in `types.ts` (glea isn't in the generator's `SERVICES`, per
  the existing GLEA convention).
- **The cross-system "ribbon" from the mock** (external Pega segments interleaved with ours) is represented as a
  scope note ("Amendia observes N of its own segments…") rather than a drawn ribbon: Phase 3A exposes only the
  segments Amendia owns (no external-segment data), so drawing external steps would be fabrication. The note
  makes the partial-observability explicit, per the ADR's honesty requirement. A future enhancement could ingest
  an orchestrator-provided segment map if one is ever available.
- No backend gaps found — the Phase-3A endpoints covered every screen.
