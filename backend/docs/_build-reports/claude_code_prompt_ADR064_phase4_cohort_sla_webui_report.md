# ADR-064 P4 — cohort SLA webui + thin SSE relay: report

**This is P4 of 4** (webui + one notification-service relay change). P1 (registry model), P2 (agent-runtime
runtime), P3 (GLEA surfacing) landed. This makes the feature **visible and live**. No agent-runtime /
process-registry / glea logic change.

## 1. Outcome

The cohort **definition** detail now has a **tabular DAG + SLA editor** (owner-gated, forward-only, server-422
as the source of truth); the cohort **instance** detail shows a **problem-focused SLA panel** (owner-attributed
summary + per-SLA chips + countdown/relative time, read from GLEA over REST); the **instances list** shows
compact breach/at-risk **badges**; and a **thin SSE signal** (`cohort_sla`, ids/labels only) invalidates the
cohort query keys so it all updates **live**. Degrading throughout (no SLA data → clean empty states). webui
`tsc` + build + `vitest` (199) green; notification-service `pytest` (19) green.

## 2. TS types (`webui/src/api/types.ts`)

- **Graph (mirrors P1):** `ExpectationGraph`, `CohortNode`/`CohortEdge`, `EdgeSla`/`NodeSla`/`EndToEndSla`, the
  `SlaOwner`/`SlaClock`/`SlaMoment`/`CohortNodeType`/`CohortSplit` unions, `START_NODE`/`CLOSE_NODE` consts, and
  `expectation_graph?: ExpectationGraph | null` on `CohortDefinition`.
- **SLA read-model (mirrors P3):** `CohortSlaEntry`, `CohortSlaBreaches`, `CohortSlaSummary` + `SlaState` union,
  `sla?: CohortSlaSummary` on `CohortDetailOut`, and `sla_breaches?`/`sla_at_risk?` on `CohortListEntry` (all
  optional/nullable → backward-compatible).
- `services/cohorts.ts`: `CohortDefinitionUpdate` gains `expectation_graph?`.

## 3. Definition DAG + SLA editor (`SlaGraphEditor.tsx` + `CohortDefinitionPage.tsx`)

- New `SlaGraphEditor.tsx` exports `SlaGraphView` (read: compact Nodes / Edges / end-to-end tables) and
  `SlaGraphEditor` (edit: add/remove nodes — a select over the definition's member pack_keys plus free-text —
  and edges — from/to selects incl. `__start__`/`__close__`, split and/xor — with per-edge/per-node/end-to-end
  **SLA field clusters** (deadline + at-risk seconds, clock, owner, edge anchor/satisfy moments)).
- Hangs off the **existing inline-edit machinery**: a new `graph` state buffer initialised from
  `def.expectation_graph` on `startEdit` (deep-cloned, cancellable), rendered inside the owner-gated `editing`
  block, and **always** included in the existing `updateCohortDefinition` PUT — `isEmptyGraph(graph) ? null :
  graph`. Full-representation/forward-only: this both adds the feature **and fixes a latent wipe** (the prior
  `onSave` omitted `expectation_graph`, which P1's full-representation PUT would have cleared on any edit).
- **Server 422 is the source of truth:** validity is validated by P1 on Save; `err.detailText` is surfaced
  inline via the existing `editError`. A light note tells the author validation runs on Save. The forward-only
  warning is reused for graph/SLA edits. Non-owners get `SlaGraphView` only (no editor) — same `isOwner` gate.

## 4. Instance SLA panel + list badges

- `CohortDetailPage.tsx`: a `SlaPanel` (rendered only when `cohort.sla` is non-empty) — an owner-attributed
  **summary** (Breaches/At-risk/Satisfied/Voided KPIs + breach-by-owner chips) and a **per-SLA table** with a
  `SlaStateChip` (breached=red, at-risk=amber pulsing, satisfied=green, voided=muted) and a `SlaTiming` cell:
  at-risk → "breaches in 42m" (`formatCountdown(due_at)`), breached → "breached 12m ago"
  (`formatRelative(detected_at)`), else muted relative. Empty/absent → no panel (never errors — P3 degrades).
- `cohortBits.tsx`: `SlaStateChip` + `SlaBadges` (a red breach count + an amber at-risk count; zero → nothing).
- `CohortsPage.tsx`: `SlaBadges` on each Instances row (from `sla_breaches`/`sla_at_risk`).

## 5. Thin SSE relay (make it live) — ids/labels ONLY

- **`notification-service/signal_mapper.py`:** `COHORT_SLA` added to `KNOWN_EVENTS`; `_ALLOWED_FIELDS` gains
  `cohort_instance_id`, `sla_id`, `state`, `owner` — **and nothing else**. No `due_at`/`at_risk_at`/`detected_at`/
  `ref`/`clock`/`correlation_value`/`cohort_def_id`/`trace` ever enters the signal (asserted by a test). One
  corollary touch in the same relay: `events/consumer.py` binds `agent_runtime.cohort_sla.v1` (an explicit
  `BINDING_KEYS` list — without the binding the mapper never sees the event, so the relay would be dead).
- **`webui/notificationsStream.ts`:** `Signal` gains `cohort_instance_id?`/`sla_id?`/`state?`/`owner?`.
- **`webui/signalToKeys.ts`:** a `case "cohort_sla"` → invalidate `["cohorts"]` (list badges) + `["cohort",
  cohort_instance_id]` (detail `sla`); `["cohorts"]`/`["cohort"]` added to `LIVE_KEYS` (caught on resync). The
  browser then re-fetches the authorized SLA data over the role-guarded GLEA REST — the signal only says which
  keys to invalidate.

## 6. Verification

- `cd webui && npx tsc --noEmit` → clean. `npm run build` → **exit 0** (built in 1.78s).
- `npx vitest run` → **199 passed** (28 files). New/updated cases:
  - `signalToKeys.test.ts`: `cohort_sla` → `["cohorts"]` + `["cohort", id]`; id-less → list only; `LIVE_KEYS`
    includes the cohort keys.
  - `features/cohorts/cohorts.test.tsx`: owner **builds a graph** (add node + edge) → Save PUT carries
    `expectation_graph`; an invalid graph's **server 422 surfaced inline**; **editing another field preserves the
    graph** in the PUT (forward-only, no wipe); instance **SLA panel** renders owner summary + chips; **no panel**
    when the cohort has no SLA data; instances list shows **breach/at-risk badges**.
- `cd backend/services/platform/notification-service && uv run --extra dev pytest` → **19 passed**, incl.
  `test_cohort_sla_signal_carries_ids_labels_only` (asserts `due_at`/`at_risk_at`/`detected_at`/`ref`/`clock`/
  `correlation_value`/`cohort_def_id`/`trace` are **absent**).
- OpenAPI/gen: GLEA + registry cohort types are **hand-written** (per `gen-api.mjs`) — the additions are additive
  and hand-mirrored; no snapshot/gen step applies. Registry snapshot (process-registry) untouched.

## 7. Follow-ups

- **Full pending-plan view (deferred):** GLEA is problem-focused (transition-derived) — still-`pending` on-track
  expectations aren't shown. A "whole declared plan with live countdowns for pending ones" view would need the
  agent-runtime `cohort_sla_expectations` snapshot exposed over a new role-guarded REST endpoint (an
  agent-runtime change) — not done in P4 per the scope decision.
- **By-correlation live update:** the `cohort_sla` signal carries `cohort_instance_id`, so it targets `["cohort",
  id]` + the list; the secondary `["cohort-by-correlation", value]` route isn't targeted (no value in the thin
  signal) — it still refreshes on its 5s poll. Add a value field only if that route needs sub-second liveness.
- **Friendlier duration UX:** the editor uses raw seconds inputs; a "2h"/"30m" parser + humanised display is a
  nice-to-have.
- **Visual DAG canvas:** deferred (tabular editor first, per ADR-064).
- **Reviewer note:** the `signal_mapper` + consumer-binding changes are live after `docker compose build
  notification-service` (+ restart); the webui is a rebuild/redeploy. (P1–P3 service rebuilds already noted.)
