# Claude Code prompt — ADR-063 Phase 3B: cohort webui (list, detail w/ member BPMN, backlink, new-cohort)

Implement **Phase 3B** of **ADR-063** — the **webui** for cohorts, coded against the Phase 3A endpoints (which
are landed + green). This is the last Phase-3 slice. Reuse existing webui components (BpmnViewer, deriveSteps,
the instance-diagram rendering, the shared UI kit) — do not reinvent them.

**Visual/interaction spec:** the mockup at `backend/docs/design/amendia_cohort_view_mockup.html` (also in the
claude.ai project under `claude/design/`) is the reference for layout and flow — the three screens plus the
New-cohort form. Match it in spirit using the real webui components/styling, not by copying its inline CSS.

## The Phase-3A endpoints you code against (already live)

- **GLEA** (`glea` service): `GET /cohorts` → `CohortListOut { count, cohorts: [CohortListEntry] }`;
  `GET /cohorts/{cohort_instance_id}` and `GET /cohorts/by-correlation/{correlation_value}` →
  `CohortDetailOut`. `CohortDetailOut` = identity (`cohort_instance_id`, `cohort_def_id`, `correlation_value`,
  `state` open|closing|closed, `member_count`, `rollup {done,running,failed}`, `opened_at`, `closed_at`,
  `outcome`, `anomalies`) + `roster: [{process_instance_id, pack_key, pack_version, correlation_id, status
  done|running|failed, started_at, ended_at, outcome, late}]` + `events: [{op, at, process_instance_id,
  detail}]` + `close: {signalled, outcome, state, late_joins}`. (See the 3A report's example JSON.)
- **Registry** (`registry` service): `POST /cohort/definitions`, `GET /cohort/definitions`,
  `GET /cohort/definitions/{id}`, `DELETE …`; `PUT /packs/{key}/{version}/cohort-membership` +`DELETE`;
  `GET /packs` (active packs); `GET /packs/{key}/{version}/trigger-fields` → `{fields: [...]}`;
  `GET /packs/{key}/{version}/bpmn` (diagram XML).
- **Runtime** (`runtime` service): `GET /instances/{id}` now includes `cohort_instance_id`, `cohort_def_id`,
  `cohort_correlation_value` (null when standalone) + `actor_log`.

Note on the roster vs rollup (deliberate 3A behaviour): a **late-join** member appears in `roster` with
`late: true` but is **excluded** from `member_count`/`rollup`. Render late members distinctly (a flag/badge) and
don't assume `roster.length === member_count`.

## Read first (reuse these)

- `webui/src/api/client.ts` (`request<T>(service, path, opts)`), `src/api/config.ts` (`ServiceKey`,
  `SERVICE_BASE`), `src/api/services/glea.ts` (the `optional()` null-on-404/503 pattern), `registry.ts`,
  `runtime.ts`, and `src/api/types.ts` / `src/api/gen/*` (regenerate with `npm run gen:api` to pick up the new
  cohort/instance types, then hand-type anything not generated).
- `webui/src/features/registry/BpmnViewer.tsx` — `BpmnViewer({ xml, markers })`,
  `BpmnMarker { elementId, state }`, states painted via `.bpmn-state-*` (done/current/pending/failed).
- `webui/src/lib/steps.ts` — `deriveSteps(pack, actor_log, { currentElementId, failedElementId })` (post
  ADR-062; `done` = actor_log membership only); `webui/src/features/task/ProcessDiagramView.tsx` +
  `useProcessProgress.ts` — how steps → `BpmnMarker[]`.
- `webui/src/features/instances/InstanceDetailPage.tsx` — the reference for rendering an instance's BPMN from
  its `actor_log` (and where the backlink banner goes); `InstancesPage.tsx`, `queries.ts` (react-query pattern).
- `webui/src/router.tsx` — route table; the shared layout/rail nav component it renders at `/` (add the
  "Cohorts" nav item there); `src/components/ui/*` — the shared card/table/pill/badge kit.

## Tasks

### 1. API + queries (`src/api/services/cohorts.ts` + a `cohorts` feature `queries.ts`)

Add typed calls: `getCohorts(state?)`, `getCohort(id)`, `getCohortByCorrelation(value)` (glea; list may be
empty — render an empty state, not an error). Registry: `listCohortDefinitions`, `createCohortDefinition`,
`assignMembership(packKey, version, {cohort_def_id, correlation_key})`, `clearMembership(...)`,
`getTriggerFields(packKey, version)`, `listActivePacks()`. Wrap read calls in react-query hooks like the other
features.

### 2. Cohort list — `cohorts` route (`CohortsPage`)

A table, one row per cohort: correlation value, cohort def, `state` chip (open/closing/closed — closing
visually distinct), a done/running/failed rollup bar + counts, opened/closed, outcome, and a `late-join`
anomaly flag. A small KPI strip (definitions, active, closed, anomalies) if cheap. A **"+ New cohort"** action
→ `cohorts/new`. Rows link to `cohorts/:cohortId`. Empty state when there are no cohorts.

### 3. Cohort detail — `cohorts/:cohortId` (`CohortDetailPage`) — the hero is member BPMN

Header (cohort id, def, `correlation_value`, state pill, outcome). Then, the centrepiece: **each roster member
rendered as its own BPMN diagram with live execution highlighting** — for each member, fetch the pack BPMN
(`GET /packs/{pack_key}/{pack_version}/bpmn`) + the member instance's `actor_log`/status
(`GET /instances/{process_instance_id}`), run `deriveSteps` → `BpmnMarker[]`, and render with `BpmnViewer`
(exactly as the instance view does — factor a small `MemberDiagram` that reuses that path). A running member
shows its current node; un-taken branches stay pending; a failed member shows the failed node — the ADR-062
precision, per member. Each member block links to its full instance view.

Below the diagrams: a compact **cross-system context** note (Amendia observed N of the total — we only see our
own segments), the **lifecycle event stream** (`events`, ordered, with the op + timestamp + detail), and a
**close** card (signalled by orchestrator, outcome, current state). Support the `by-correlation` route too if
cheap. Degrade gracefully when a member's BPMN/instance is unavailable (show the roster row, not a crash).

### 4. Instance backlink banner (`InstanceDetailPage`)

When `GET /instances/{id}` returns a non-null `cohort_instance_id`, render a banner at the top: "Part of cohort
`{cohort_def_id}` · `{cohort_instance_id}` · N sibling segments → View cohort" linking to
`cohorts/{cohort_instance_id}`. Nothing renders for a standalone instance. Keep the rest of the page unchanged.

### 5. New cohort + membership — `cohorts/new` (`NewCohortPage`)

Two sections in one flow (mirrors the mock): (a) **definition** — `cohort_def_id`, display name/description,
the close-message JSON Schema (a code/textarea), and the correlation/outcome dotpaths → `POST
/cohort/definitions`. (b) **members** — list active packs (`listActivePacks`), each with an Add toggle and a
**per-pack correlation-key selector** populated from `getTriggerFields(pack, version)` (fall back to a free
dotpath input when a pack declares no trigger fields); on save, `PUT …/cohort-membership` for each assigned
pack. Validate: def id present, close schema parses as JSON, each assigned pack has a correlation key. On
success → the list (or the new cohort's definition). Also expose "Manage membership" from the detail page.

### 6. Routing + nav

Add routes to `router.tsx`: `cohorts` (list), `cohorts/new`, `cohorts/:cohortId` (detail). Add a **Cohorts**
nav item to the shared rail (near Instances). Keep the existing routes untouched.

## Tests (vitest + testing-library, matching the existing feature tests)

- Cohort list renders rows + rollup + state chips from a mocked `CohortListOut`; empty state when `count: 0`.
- Cohort detail renders the roster, one `MemberDiagram` per member (BpmnViewer mocked), the event stream, and
  the close card from a mocked `CohortDetailOut`; a `late: true` member shows the late badge and the header
  `member_count` can differ from `roster.length`.
- Instance page shows the backlink banner when `cohort_instance_id` is present, and **not** when it's null.
- New-cohort form: assigning a pack loads its trigger fields into the key selector; submit calls
  `createCohortDefinition` + `assignMembership` per pack (mocked); JSON-schema-parse validation blocks submit.
- `npm run typecheck`, `npm run gen:api:check` (regenerate first), and the webui test suite green.

## Do not

- Do not reinvent BPMN rendering or step derivation — reuse `BpmnViewer` + `deriveSteps` + the instance
  diagram path. Do not restore any "terminal → all done" behaviour (ADR-062).
- Do not change the Phase-3A endpoints or any backend; this is webui-only. If you find a genuine backend gap,
  note it in the report rather than patching backend here.
- Do not block the whole detail page when one member's BPMN/instance is unavailable (per-member graceful
  degrade), and treat the `glea` cohort calls as they may 404/503 (empty/unavailable state, not a crash).
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- Cohorts list → detail → member BPMN diagrams (live-highlighted per member) → instance (with a working
  backlink) all navigate, coded against the real Phase-3A responses.
- New cohort registers a definition and assigns membership to selected active packs with per-pack correlation
  keys, via the registry endpoints.
- Late-join members render distinctly; closing/closed states and the outcome show correctly; empty/unavailable
  states degrade gracefully.
- `typecheck` + `gen:api:check` + webui tests green.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR063_phase3b_cohort_webui_report.md` (uncommitted):
(1) outcome one-liner; (2) files/pages added (list, detail, new, backlink) and which existing components were
reused (BpmnViewer, deriveSteps, the instance-diagram path); (3) how member diagrams fetch + derive state;
(4) routing/nav additions; (5) tests; (6) verification (typecheck, gen:api:check, tests) + results; (7)
anything left open. Note this **completes ADR-063 Phase 3 (and the ADR end-to-end: runtime → close → read →
UI)**. Keep it to a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Reuse existing components and styling; the mock is a
spec, not CSS to paste. Stay inside `webui/`.
