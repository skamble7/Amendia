# Claude Code prompt — ADR-064 P4: cohort SLA **webui** (tabular DAG+SLA editor, instance rendering, SSE signal relay)

Final phase of **ADR-064 (Cohort SLAs)**. P1 (registry model+validation), P2 (agent-runtime timers/evaluation),
P3 (GLEA surfacing) are done. P4 makes it **visible and live**: a **tabular DAG + SLA editor** on the cohort
**definition** detail (owner-gated, forward-only), **at-risk/breached rendering** on the cohort **instance**
(read from GLEA over REST), **list badges**, and the **thin SSE signal relay** so it updates live. Read
`backend/docs/adr/ADR-064-*.md` and the authoring guide (`backend/docs/methodology/cohort_authoring_guide.html`)
— the guide is the spec for the editor's semantics.

Mostly **webui**, plus one **minimal, isolated** `notification-service` change (the SSE relay). No agent-runtime /
process-registry / glea logic changes (P1–P3 done).

**Security boundary (hard rule):** the SSE signal carries **ids/labels only** — `cohort_instance_id`, `sla_id`,
`state`, `owner` — and **never** timing/business content (no `due_at`, `at_risk_at`, deadlines, schema). The
browser uses the signal only to invalidate query keys, then re-fetches the authorized SLA data over the
**role-guarded GLEA REST** endpoints. Keep `signal_mapper` a strict whitelist.

**Scope decision (Sandeep):** the instance SLA view is **problem-focused / transition-derived** — it shows
at-risk / breached / satisfied / voided (from P3's GLEA read-model). Still-`pending` on-track expectations are
**not** shown (they live only in the agent-runtime snapshot SoR). Do **not** add an agent-runtime snapshot
endpoint or a full pending-plan view in P4 — that's an optional later follow-up. Visual DAG canvas: later.

## Read first

- `webui/src/api/types.ts` — hand-written types. `CohortDefinition` (**no `expectation_graph` yet**),
  `CohortDetailOut` (**no `sla` yet**), `CohortListEntry`/`CohortListOut`. Add the SLA/graph shapes here
  (mirror P1's `models/cohort.py` and P3's read-model).
- `webui/src/features/cohorts/CohortDefinitionPage.tsx` — the owner-gated definition detail with the existing
  inline `editing`/`form` machinery, `onSave` -> `updateCohortDefinition`, the Members table, and the forward-only
  warning. Extend the editor with the DAG+SLA section; extend `onSave`'s payload with `expectation_graph`.
- `webui/src/features/cohorts/CohortDetailPage.tsx` — the instance detail (KPIs + per-member diagrams). Add the
  SLA panel here.
- `webui/src/features/cohorts/CohortsPage.tsx` — the Instances list (+ Definitions tab). Add the row SLA badges.
- `webui/src/features/cohorts/{queries.ts,membership.tsx}` + `webui/src/api/services/cohorts.ts` — query keys
  (`["cohorts", state]`, `["cohort", id]`), the existing `CorrelationKeySelect`/inputs to reuse. `getCohort` /
  `getCohorts` already return `CohortDetailOut` / list — the new `sla` fields ride along once typed.
- `webui/src/api/signalToKeys.ts` + `webui/src/api/notificationsStream.ts` + `app/NotificationsProvider.tsx` —
  the thin-signal -> query-key mapping and the `Signal` type. Add a `cohort_sla` case + `cohort_instance_id` field.
- `backend/services/platform/notification-service/app/events/signal_mapper.py` — `KNOWN_EVENTS` +
  `_ALLOWED_FIELDS` + `to_signal`. Add the `COHORT_SLA` event + whitelist the id/label fields.
- The `CohortSlaEvent`/`COHORT_SLA` routing constant (in `amendia_common.events` / `amendia_contracts`, added
  P2/P3) — reuse.

## Deliverables

### 1. Types (`webui/src/api/types.ts`)
- Mirror P1's graph: `ExpectationGraph { nodes: CohortNode[]; edges: CohortEdge[]; end_to_end_sla?: EndToEndSla }`,
  `CohortNode { node_id; node_type: "expected"|"conditional"; runtime_sla?: NodeSla }`,
  `CohortEdge { from_node; to_node; split: "and"|"xor"; sla?: EdgeSla }`, `EdgeSla`/`NodeSla`/`EndToEndSla`
  (deadline_seconds, at_risk_seconds, clock: "wall"|"business", owner: "external"|"amendia"|"shared",
  edge also anchor_moment/satisfy_moment: "arrival"|"completion"). Add `expectation_graph?: ExpectationGraph | null`
  to `CohortDefinition`.
- Mirror P3's read-model: an `sla` section on `CohortDetailOut` — a per-SLA current-state list
  (`sla_id, kind, ref, owner, clock, state: "at_risk"|"breached"|"satisfied"|"voided", due_at, at_risk_at,
  detected_at`) + summary (`breaches: {external, amendia, shared, total}`, `at_risk`, `satisfied`, `voided`),
  all optional/nullable. Add `sla_breaches?: number; sla_at_risk?: number` to `CohortListEntry`.

### 2. Definition detail — tabular DAG + SLA editor (owner-gated, forward-only)
- **Read view:** when a definition has an `expectation_graph`, render it as compact tables — a Nodes table
  (node_id, type, runtime SLA summary) and an Edges table (from -> to, split, SLA summary `owner · deadline ·
  clock`), plus the end-to-end SLA. When absent, show a short "no SLAs declared" empty state.
- **Edit view** (inside the existing owner-gated `editing` mode): tabular editors to add/remove **nodes**
  (node_id — a select over the definition's member pack_keys where available, else free text; node_type) and
  **edges** (from_node/to_node selects incl. `__start__`/`__close__`; split and/xor), with per-edge and per-node
  **SLA fields** (deadline + at-risk as a simple duration input, clock wall/business, owner, and edge
  anchor/satisfy moments) and the optional end-to-end SLA. On **Save**, include `expectation_graph` in the
  existing `updateCohortDefinition` payload (P1's `PUT`, forward-only, full-representation). **Server 422 is the
  source of truth** for graph validity — surface `err.detailText` inline (a light client-side check for obvious
  gaps is fine, but don't reimplement P1's validator). Reuse the existing forward-only warning (edits affect
  future cohorts only) for graph/SLA edits too.

### 3. Instance detail — SLA panel (problem-focused, from GLEA over REST)
- If `cohort.sla` is present and non-empty, render an **SLA panel**: an owner-attributed **summary** (breaches by
  external/amendia/shared, at-risk count) and a per-SLA list with a **state chip** (at-risk = amber, breached =
  red, satisfied/voided = muted/green), the **owner**, and a **next-deadline countdown / relative time** from
  `at_risk_at`/`due_at` (e.g. "breaches in 42m", or "breached 12m ago" using `detected_at`). Empty/hidden when
  the cohort has no SLA data — never error (P3 degrades to empty).

### 4. Instances list — SLA badges
- On the Instances tab rows, show compact badges from `sla_breaches`/`sla_at_risk` (e.g. a red "2" breach badge,
  an amber at-risk badge) so operators can spot cohorts in trouble at a glance. Zero -> no badge.

### 5. Thin SSE signal relay (make it live)
- **Backend (`notification-service/signal_mapper.py`):** add `COHORT_SLA` to `KNOWN_EVENTS` and whitelist
  `cohort_instance_id`, `sla_id`, `state`, `owner` in `_ALLOWED_FIELDS` (ids/labels only — **no** `due_at`/
  `at_risk_at`/`detected_at`/deadlines). This is the ONLY notification-service change.
- **webui `notificationsStream.ts`:** add `cohort_instance_id` (and optional `sla_id`/`state`/`owner`) to the
  `Signal` type.
- **webui `signalToKeys.ts`:** add a `case "cohort_sla"` -> invalidate `["cohorts"]` (list) and, when present,
  `["cohort", cohort_instance_id]` (detail). Add `["cohorts"]` + `["cohort"]` to `LIVE_KEYS` (caught on
  reconnect/resync). The browser then re-fetches the authorized SLA data over REST.

## Do not

- Do not change P1–P3 backend logic; the only backend touch is the `signal_mapper` whitelist. Do not put any
  SLA timing/business data into the SSE signal — ids/labels only; REST carries the data.
- Do not add an agent-runtime snapshot endpoint or a full pending-plan view (deferred). No visual DAG canvas.
- Do not ungate the editor — DAG/SLA editing stays `isOwner` (process-owner), inline, forward-only, like the rest
  of the definition editor. Non-owners see the read view only.
- Keep everything **degrading**: no SLA data -> clean empty states, never an error.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- As **priya** (process-owner) on a definition detail: enter edit mode, build a small graph
  (`__start__ -> A -> B -> __close__`, an edge SLA + the end-to-end SLA), **Save** -> `PUT` carries
  `expectation_graph`; the read view reflects it; a deliberately invalid graph (e.g. XOR branch marked expected)
  surfaces the server **422** message inline. A non-owner sees the read view, no editor.
- On a cohort **instance** with SLA data (from GLEA): the SLA panel shows the owner-attributed summary + per-SLA
  chips + a countdown/relative time; a cohort with no SLA data shows no panel (and no error).
- The **Instances list** shows breach/at-risk badges on cohorts that have them; none on those that don't.
- **Live update:** a `cohort_sla` SSE signal invalidates `["cohorts"]` and `["cohort", id]` (unit-tested in
  `signalToKeys.test.ts`); the `signal_mapper` emits only the whitelisted ids/labels (backend test — asserts
  `due_at`/timing are **absent**).
- `tsc` + `npm run build` clean; `vitest` green incl. the new editor / instance-panel / list-badge / signalToKeys
  cases; notification-service `pytest` green incl. the whitelist test.
- **Reviewer note:** the `signal_mapper` change is live after `docker compose build notification-service`; the
  webui is a rebuild/redeploy. (P1–P3 service rebuilds already noted.)

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR064_phase4_cohort_sla_webui_report.md` (uncommitted):
(1) outcome one-liner; (2) the TS types added (graph + `sla`); (3) the definition DAG+SLA editor (read + edit,
how it hangs off the existing inline-edit machinery, server-422 surfacing); (4) the instance SLA panel + list
badges; (5) the SSE relay (the `signal_mapper` whitelist + `signalToKeys` case) and confirmation the signal is
ids/labels-only; (6) verification — exact `tsc`/`vitest`/`pytest`/build commands + results; (7) any follow-ups
(e.g. the deferred snapshot/full-plan endpoint, a friendlier duration UX, the visual canvas). One screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. webui + the one `signal_mapper` whitelist only. Reuse
the existing inline-edit machinery, `CorrelationKeySelect`/inputs, the forward-only warning, and the
signal->keys pattern. Owner-gated, forward-only, degrading, and — for the SSE — **thin signal + REST for data**.
This lands the feature end-to-end and visible.
