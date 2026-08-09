# Dedicated Cohort Definitions surface; membership moved off the instance: report

## 1. Outcome

Cohort **instances** (runtime observability) and **definitions** (design-time config) are now separate surfaces.
The Cohorts page has an **Instances | Definitions** segmented control (Instances default, URL-persisted);
membership is managed on a new **definition detail** page, not on an immutable instance. The instance detail's
misleading "Manage membership" button is replaced by a read-only link to its definition. webui-only — **no
backend changes** (every endpoint already existed).

## 2. Changes by file

- **`features/cohorts/membership.tsx`** (new): extracted the shared `CorrelationKeySelect` (trigger-fields select
  / free-dotpath fallback, now used by both the New-cohort form and the definition editor) + helpers
  `membersOf(def, packs)`, `unassignedPacks(packs)`, `closeMatch(def)`.
- **`features/cohorts/CohortsPage.tsx`**: added the `?tab=instances|definitions` segmented control (`useSearchParams`,
  Instances default). Split into `InstancesTab` (the existing list + its 4 KPIs, unchanged) and a new
  `DefinitionsTab` (table over `useCohortDefinitions`: **Cohort id**, **Display name**, **Members**, **Close match**
  `event=… → path`, **Instances** `N · M closed`, **Manage**; + a definitions KPI strip). Exports the reused `Kpi`.
  The primary **`+ New cohort`** action now shows only on the Definitions tab (empty state offers it too).
- **`features/cohorts/CohortDefinitionPage.tsx`** (new, route `cohorts/definitions/:cohortDefId`): resolves the
  definition from `useCohortDefinitions()` by id (404-style empty state if absent). Header (mono id + display
  name, Active chip, `Cohorts / Definitions / <id>` breadcrumb, owner-gated **Edit** → `/cohorts/new` and
  **Delete**). Read-only **Definition** panel (correlation/outcome paths + pretty-printed `close_schema`). The
  relocated **Members** editor (per-row `CorrelationKeySelect` → `assignMembership` PUT overwrite, **Remove** →
  `clearMembership` DELETE, **+ Add pack** over unassigned active packs) with the **forward-only** warning. A
  read-only **Instances** panel (`useCohorts` filtered by `cohort_def_id`, rows → instance detail).
- **`features/cohorts/CohortDetailPage.tsx`**: removed the `navigate("/cohorts/new")` "Manage membership" button;
  added a read-only `Definition: <cohort_def_id> ↗` link → `/cohorts/definitions/:id` (mirrors the backlink
  styling). Dropped the now-unused `Button`/`useNavigate`.
- **`features/cohorts/NewCohortPage.tsx`**: its inline correlation-key control now reuses `CorrelationKeySelect`.
- **`api/services/cohorts.ts`**: added `deleteCohortDefinition` (the registry `DELETE /cohort/definitions/{id}`
  already exists, owner-gated + idempotent).
- **`router.tsx`** + **`test/renderApp.tsx`**: registered `cohorts/definitions/:cohortDefId` (before `:cohortId`).

## 3. Counts derived client-side (no backend touched)

- A definition's **members** = `useActivePacks()` filtered to `cohort_membership.cohort_def_id === cohort_def_id`.
- A definition's **instances** = `useCohorts()` rows filtered by `cohort_def_id` (+ a `state==='closed'` sub-count).
- KPIs: definitions from `useCohortDefinitions`, members-total/unassigned from active packs, instances from the
  glea list. No new endpoint; the definitions data (`useCohortDefinitions`) was already loaded for a KPI and is
  now first-class. `useActivePacks` mounts only inside the Definitions tab / definition page (Instances tab is
  unaffected — the existing instances list keeps its exact fetch shape).

## 4. V1 forward-only membership decision

Membership edits are **forward-only** — they change which future spawns join; they never re-home or detach an
already-running/closed member. When the definition has ≥1 instance, a **non-blocking** amber inline warning
renders above the Members table stating exactly that. No versioning, no edit-blocking, no detach — the deeper
membership-versioning work is the parked **CB-6** backlog item (out of scope). Mutations invalidate
`["cohort-definitions"]`, `["active-packs"]`, and `["cohorts","all"]` so the editor + tab counts refresh without
a manual reload.

## 5. Verification

- `npx tsc --noEmit` → **clean**.
- `npx vitest run` → **28 files / 188 tests passed** (+5 cohort tests; existing suites unaffected).
- `npx eslint` on the touched cohort files + router + renderApp → **0 problems**.
- New tests (`features/cohorts/cohorts.test.tsx`): Instances-default → flip to Definitions (URL-persisted) with
  the close-match string; `?tab=definitions` shows `ach_exposure_cohort` **Members=3 / Instances=1**; definition
  detail renders members + pretty `close_schema` + the forward-only warning + the instances panel; **Remove then
  Add** round-trips against the registry (DELETE then PUT captured, member list updates via refetch); instance
  detail shows the read-only **Definition:** link and **no** "Manage membership" button.

## 6. Follow-ups (optional)

- A per-definition `GET /cohort/definitions/{id}` would let the detail page avoid scanning the list — cheap now
  (definitions are few), so deferred.
- **Delete-definition** is wired (the endpoint exists); if the team prefers definitions be undeletable while
  instances exist, add a guard server-side (not done here — out of scope).
- Deeper membership semantics (versioning / re-home / detach) remain **CB-6**.
