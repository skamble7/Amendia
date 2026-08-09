# Claude Code prompt — dedicated Cohort **Definitions** surface; move membership management off the instance

webui-only change to the ADR-063 cohorts feature. Today the **Cohorts** page lists cohort **instances**
(runtime observability), and membership is (mis)managed from an **instance's** detail via a "Manage membership"
button that actually just routes to `/cohorts/new`. That's a category error: membership is a property of the
**definition** (design-time config), not of an immutable runtime **instance**.

Split the two surfaces: keep instances read-only, and give **definitions** their own list + detail where
membership is managed. No backend changes — every endpoint already exists.

## Why

- A cohort **instance** is an observed fact (it already ran / is running). You should never "edit membership" from
  it. A cohort **definition** is the thing an owner maintains.
- The current "Manage membership" button on the instance detail (`CohortDetailPage.tsx`) navigates to
  `/cohorts/new`, which is misleading and can't edit an existing definition's members at all.
- We already load `useCohortDefinitions()` on the Cohorts page (only to compute a KPI). Promote definitions to a
  first-class surface.

## Read first (reuse, don't rewrite)

- `webui/src/features/cohorts/CohortsPage.tsx` — the current instances list. Already imports
  `useCohorts` + `useCohortDefinitions`; the `+ New cohort` button and KPIs live here.
- `webui/src/features/cohorts/CohortDetailPage.tsx` — the **instance** detail. Line ~102 is the
  `Manage membership` button (`onClick={() => navigate("/cohorts/new")}`) to remove.
- `webui/src/features/cohorts/NewCohortPage.tsx` — the definition-create form incl. the **membership picker**
  (pack list, trigger-fields → correlation-key, Add). Reuse its picker for the definition-detail editor rather
  than reinventing it — extract a shared component if that's cleaner.
- `webui/src/features/cohorts/CohortBacklink.tsx` — the existing instance→cohort banner pattern (styling to
  mirror for the new read-only backlink).
- `webui/src/api/services/cohorts.ts` + `webui/src/features/cohorts/queries.ts` — **all** the data access is
  already here: `listCohortDefinitions` / `useCohortDefinitions`, `createCohortDefinition`, `assignMembership`
  (PUT), `clearMembership` (DELETE), `getTriggerFields` / `useTriggerFields`, `listActivePacks` /
  `useActivePacks`, and the glea reads `useCohorts` / `useCohort`.
- `webui/src/api/types.ts` — `CohortDefinition` (`cohort_def_id`, `display_name`, `description`, `close_schema`,
  `close_correlation_path`, `close_outcome_path`) and `ProcessPackManifest.cohort_membership`
  (`{cohort_def_id, correlation_key}`).
- `webui/src/router.tsx` — the `cohorts/*` routes.
- The proposed UX: `backend/docs/design/amendia_cohort_definitions_ux_mockup.html` (Instances tab first &
  default; Definitions tab; definition detail with the Members editor; revised instance detail backlink).

**No new backend endpoints.** Member lists per definition are derived client-side: a definition's members =
active packs whose `cohort_membership.cohort_def_id === cohort_def_id` (from `useActivePacks`). A definition's
instances = `useCohorts()` rows filtered by `cohort_def_id`.

## Deliverables

### 1. Cohorts page — segmented tabs: **Instances** | **Definitions**
- Add a two-option segmented toggle at the top of `CohortsPage`. **Order: Instances first and default**, then
  Definitions. Persist the choice in the URL (e.g. `?tab=instances|definitions` via `useSearchParams`) so it's
  linkable and survives refresh; default (no param) = Instances.
- **Instances tab:** the existing list + its KPIs, unchanged.
- **Definitions tab (new):** a table over `useCohortDefinitions()` — columns: **Cohort id** (mono), **Display
  name**, **Members** (count of active packs mapped to it), **Close match** (`{close_schema event const} ->
  {close_correlation_path}`, e.g. `event=process_completed -> case_id`), **Instances** (count from `useCohorts`,
  with a "N closed" sub-count if easy), and a **Manage** action -> definition detail. Row click also navigates to
  the definition detail. Include a small KPI strip appropriate to definitions (e.g. Definitions registered,
  Members total, Instances, Packs unassigned) — reuse the existing `Kpi` component.
- Move the primary **`+ New cohort`** action so it reads as "new definition": show it on the **Definitions**
  tab header (it already routes to `/cohorts/new`). Empty-state on the Definitions tab offers the same action.

### 2. Definition detail — new route + page (membership lives here)
- New route `cohorts/definitions/:cohortDefId` -> `CohortDefinitionPage` (new file
  `webui/src/features/cohorts/CohortDefinitionPage.tsx`). Resolve the definition from `useCohortDefinitions()`
  by id (no per-id endpoint needed); 404-style empty state if not found.
- **Header:** `cohort_def_id` (mono) + display name, an "Active" chip, breadcrumb `Cohorts / Definitions / <id>`,
  and owner-gated actions (`Edit definition` -> `/cohorts/new` reused, and `Delete` — wire only if a delete
  endpoint already exists; otherwise omit the Delete button, don't invent one).
- **Definition panel (read-only view):** `close_correlation_path`, `close_outcome_path`, and the `close_schema`
  rendered as pretty JSON (reuse whatever JSON/code block the NewCohortPage uses).
- **Members panel (the relocated management):** table of the definition's member packs — pack key `@version`,
  its trigger match if readily available, **correlation key** (mono), and per-row **Change key** (a
  `useTriggerFields`-backed select -> `assignMembership` PUT, which overwrites) and **Remove** (`clearMembership`
  DELETE). A **+ Add pack** control lists active packs **not already** mapped to any cohort, lets the user pick a
  correlation key from that pack's trigger fields, and calls `assignMembership`. After any mutation, invalidate
  the `["cohort-definitions"]` and `["active-packs"]` query keys so the list + counts refresh.
  - **V1 semantics (keep simple):** membership edits are **forward-only** — they affect which future spawns
    join, and never re-home or detach an already-running/closed member. If the definition has >=1 instance, show
    a **non-blocking** inline warning to that effect above the Members table. Do **not** build versioning or
    block edits — deeper membership-versioning is the parked **CB-6** backlog item, explicitly out of scope.
- **Instances-of-this-definition panel (read-only):** `useCohorts()` filtered by `cohort_def_id`, each row
  linking to the instance detail `/cohorts/:cohort_instance_id`. Degrades to an empty/"none yet" state when GLEA
  is unavailable (the reads are already `optional`).

### 3. Instance detail — replace "Manage membership" with a read-only definition backlink
- In `CohortDetailPage.tsx`, **remove** the `Manage membership` button (the `navigate("/cohorts/new")` one).
- In its place, render a read-only **link to the definition**: `Definition: <cohort_def_id>` ->
  `/cohorts/definitions/:cohort_def_id` (mirror the `CohortBacklink` styling; the instance already carries
  `cohort_def_id`). This is navigational only — no editing from the instance.

## Do not

- No backend changes — reuse the existing registry/glea endpoints and the existing service/query functions. If
  you believe an endpoint is genuinely missing, STOP and report rather than adding one.
- Don't touch the observability semantics: the instances list, rollups, `MemberDiagram`/ADR-062 highlighting,
  and the `CohortBacklink` banner all stay as-is (you only swap the instance-detail button for a link).
- Don't build membership versioning, edit-blocking, or "detach a running member" — forward-only + a warning is
  the V1 scope (CB-6 owns the rest).
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- `/cohorts` opens on **Instances** by default; the segmented control flips to **Definitions**; the choice is in
  the URL and survives refresh.
- Definitions tab lists `ach_exposure_cohort` with Members = 3 and Instances = 1; clicking it (or **Manage**)
  opens `/cohorts/definitions/ach_exposure_cohort`.
- On the definition detail: **Remove** a member then **+ Add** it back (picking `case_id`) round-trips and the
  Members count + Definitions-tab count update without a manual reload; the close schema + paths render.
- The instance detail (`coh-...`) shows a read-only **Definition: ach_exposure_cohort** link and **no**
  "Manage membership" button; the link lands on the definition detail.
- `npm run build` (or the repo's typecheck) is clean; `webui/src/features/cohorts/cohorts.test.tsx` updated for
  the moved control + new views and green.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_cohort_definitions_screen_report.md` (uncommitted):
(1) outcome one-liner; (2) changes by file (new `CohortDefinitionPage`, `CohortsPage` tabs, router,
`CohortDetailPage` button->link, any extracted membership-picker component); (3) how member/instance counts are
derived client-side (confirm no backend touched); (4) the V1 forward-only membership decision + where the
warning shows; (5) verification — build/typecheck + test commands and results; (6) any follow-ups (e.g. a
per-definition GET endpoint if the client-side derivation feels heavy, Delete-definition wiring if/when the
endpoint exists). Keep it to a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. webui-only; reuse the existing services, queries, and
`NewCohortPage` membership picker. Smallest change that cleanly separates definitions from instances.
