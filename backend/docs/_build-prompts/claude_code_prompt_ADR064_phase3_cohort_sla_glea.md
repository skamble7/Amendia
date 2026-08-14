# Claude Code prompt — ADR-064 P3: cohort SLA **GLEA surfacing** (glea-service, backend-only)

Third phase of **ADR-064 (Cohort SLAs)**. P2 emits `CohortSlaEvent` on `agent_runtime.cohort_sla.v1` and holds
the authoritative per-expectation SLA state in agent-runtime Mongo (the SoR). P3 makes GLEA the **observability
read surface**: consume the event into its own ClickHouse table, derive a **current-state + owner-attributed
breach** read-model, and expose it on the cohort REST endpoints the UI already uses. **glea-service only** — no
SSE / notification-service / webui (that's P4), no agent-runtime change (P2 done). Read `backend/docs/adr/ADR-064-*.md`.

**Security boundary (unchanged):** the UI fetches authorized SLA data over **role-guarded REST** (these GLEA
endpoints). The thin SSE invalidation signal is a **P4** step (extend `notification-service/signal_mapper.py`);
P3 adds **no** SSE. GLEA stays observability-grade (derived from the fail-soft event stream); the agent-runtime
Mongo state remains the SoR — exactly the ADR-063 `cohort_events` split.

## Why

Cohorts are already surfaced from GLEA (`GET /cohorts`, `/cohorts/{id}`, `/cohorts/by-correlation/{value}`), so
the SLA view belongs there too — one cohort read surface for the UI. GLEA consumes `CohortSlaEvent` into its own
table (like `cohort_events`), and the cohort detail/list gain an SLA section with the **who-was-late** rollup.

## Read first (mirror the ADR-063 cohort_events plumbing exactly)

- `backend/services/platform/glea-service/app/events/consumer.py` — `AUDIT_BINDING_KEYS` (add the
  `agent_runtime.cohort_sla.v1` key, sibling of `rk(Service.AGENT_RUNTIME, COHORT_LIFECYCLE)`). Requeue-on-outage
  / drop-on-unmappable semantics are already handled generically.
- `backend/services/platform/glea-service/app/main.py` — the `handle(routing_key, payload)` dispatch:
  `if is_cohort_event -> cohort_writer.insert(to_cohort_row(...))`. Add a **third** branch for cohort-SLA events.
- `backend/services/platform/glea-service/app/events/mapper.py` — `is_cohort_event` / `to_cohort_row`. Add
  `is_cohort_sla_event` / `to_cohort_sla_row` beside them (map the `CohortSlaEvent` payload -> a table row).
- `backend/services/platform/glea-service/app/clickhouse/schema.py` — the `cohort_events` DDL + `COHORT_*`
  column tuples + the empty idempotent migration stub. Add a **`cohort_sla_events`** table the same way
  (ReplacingMergeTree, idempotent by `event_id`).
- `backend/services/platform/glea-service/app/clickhouse/writer.py` — `CohortWriter`. Add a sibling
  **`CohortSlaWriter`** (own table, `StorageUnavailable`->requeue, idempotent).
- `backend/services/platform/glea-service/app/clickhouse/reader.py` — `CohortReader.cohort_events_for(...)`
  etc. Add SLA reads + the current-state/rollup derivation.
- `backend/services/platform/glea-service/app/readmodels.py` — the pure cohort read-model functions (Phase 3A).
  Add the SLA summary/rollup pure functions here.
- `backend/services/platform/glea-service/app/models/cohort.py` — `CohortDetailOut` / list item / `CohortRollup`.
  Extend with the SLA views.
- `backend/services/platform/glea-service/app/routers/cohorts.py` — the three cohort endpoints to extend.
- `CohortSlaEvent` / `CohortSlaKind` / `CohortSlaState` in `amendia_contracts` (added in P2) — the payload shape
  (`state` in at_risk/breached/satisfied/voided, `cohort_instance_id`, `cohort_def_id`, `correlation_value`,
  `sla_id`, `kind`, `ref`, `owner`, `clock`, `due_at`, `at_risk_at`, `detected_at`). Reuse; don't redefine.

## Deliverables

### 1. Consume `CohortSlaEvent` -> `cohort_sla_events` (its own table)
- Bind `agent_runtime.cohort_sla.v1` in the GLEA consumer; add the `is_cohort_sla_event` branch in `handle` ->
  `cohort_sla_writer.insert(to_cohort_sla_row(routing_key, payload))`.
- New **`cohort_sla_events`** ClickHouse table (schema.py DDL + insert-column tuple + empty migration stub):
  `event_id`, `occurred_at`, `ingested_at`, `state` (LowCardinality), `cohort_instance_id`, `cohort_def_id`,
  `correlation_value`, `sla_id`, `kind`, `ref`, `owner` (LowCardinality), `clock`, `due_at`, `at_risk_at`,
  `detected_at`. `ENGINE = ReplacingMergeTree(ingested_at)`, `ORDER BY (cohort_instance_id, sla_id, occurred_at,
  event_id)` (so the latest state per `sla_id` is cheap to derive). **`audit_events` and `cohort_events` are
  untouched.** Wire `CohortSlaWriter` into `main.py` startup (mirror `cohort_writer`).

### 2. Reader + read-model: current state per SLA + owner-attributed rollup
- Reader: `cohort_sla_events_for(cohort_instance_id)` (+ `_by_correlation_value` if the by-correlation endpoint
  needs it), raising `StorageUnavailable` on a CH error like the cohort reader.
- Pure read-model functions (`readmodels.py`): from a cohort's SLA event rows, derive the **current state per
  `sla_id`** = the latest event by `(occurred_at, event_id)` (states are monotonic: pending->at_risk->
  breached/satisfied/voided, so latest wins; `owner`/`kind`/`ref`/`clock`/`due_at` are stable per `sla_id`), and
  a **breach rollup grouped by owner** (`{external, amendia, shared, total}`) plus `at_risk` / `satisfied` /
  `voided` counts.

### 3. Surface on the cohort endpoints (what the UI reads over REST)
- **`CohortDetailOut`** gains an `sla` section: the per-SLA current-state list
  (`sla_id, kind, ref, owner, clock, state, due_at, at_risk_at, detected_at`) + the summary counts (breaches by
  owner, at-risk, satisfied, voided). Empty/absent when the cohort has no SLA events.
- **Cohort list item** gains a compact SLA badge count (e.g. `sla_breaches` total + `sla_at_risk`) so the list
  can flag cohorts in trouble without a per-row fetch. Reuse the existing list query shape; degrade to zero when
  there are no SLA events.
- All three endpoints (`GET /cohorts`, `/cohorts/{id}`, `/cohorts/by-correlation/{value}`) stay
  **optional/degrading** — a cohort with no SLA data returns the same shape as today with empty SLA fields
  (backward-compatible; existing consumers unaffected).

### Scope note (deliberate)
GLEA surfaces SLA state **derived from emitted transitions** (at_risk/breached/satisfied/voided). Expectations
still `pending` and never transitioned are *not* in GLEA (they live in the agent-runtime snapshot SoR) — which is
correct for an observability/accountability view (it shows problems, resolutions, and attribution). A full
"every expectation incl. still-pending, with live countdowns" view would need the agent-runtime snapshot exposed
over REST — **out of scope for P3**; flag it as a possible P4 follow-up if the UI wants the full plan. Likewise,
do **not** repurpose the existing global `audit` `sla_breaches` metric — keep cohort SLA counts on the cohort
surface (unifying them is a separate, optional decision).

## Do not

- Do not touch **agent-runtime** (P2 done), **notification-service**, or **webui** (P4). No SSE / `signal_mapper`.
- Do not modify `audit_events` or `cohort_events` (their tables/writers/readers) — the SLA table is its own.
- Do not redefine the `CohortSlaEvent` contract — import it from `amendia_contracts`.
- Do not change the existing cohort rollup (done/running/failed) semantics.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- A `CohortSlaEvent` published on `agent_runtime.cohort_sla.v1` is persisted to `cohort_sla_events`, idempotent
  by `event_id` (a redelivery inserts no duplicate after merge).
- **Current-state derivation:** for one `sla_id`, events `at_risk` then `breached` -> current state `breached`;
  `at_risk` then `satisfied` -> `satisfied`. The **owner rollup** counts a breached external-owned SLA under
  `external`, an amendia-owned one under `amendia`.
- `GET /cohorts/{id}` returns the `sla` section (per-SLA state + owner-attributed counts); `GET /cohorts` list
  rows carry the compact breach/at-risk counts; a cohort with **no** SLA events returns empty SLA fields and is
  otherwise unchanged.
- GLEA reads **degrade** (empty, not error) when ClickHouse is unavailable, like the other cohort reads.
- `pytest` (glea-service) green incl. the above; the OpenAPI snapshot re-dumped + `gen/glea.ts` (or the glea
  client) regenerated so `webui` `tsc`/build stays green — the UI doesn't render the fields until P4, but the
  generated types must compile.
- **Reviewer note:** live only after `docker compose build glea-service` (+ restart); the new table bootstraps
  idempotently on startup (CREATE TABLE IF NOT EXISTS).

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR064_phase3_cohort_sla_glea_report.md` (uncommitted):
(1) outcome one-liner; (2) consumer binding + `handle` branch + mapper; (3) the `cohort_sla_events` table (DDL,
engine, order-by) + writer; (4) reader + the current-state/owner-rollup derivation (how "latest per sla_id" is
computed); (5) the endpoint/response-model additions (detail `sla` section + list badges) + backward-compat
(empty when no SLA data); (6) verification — exact `pytest` + snapshot/gen + webui build commands & results;
(7) follow-ups for **P4**: the exact `signal_mapper` whitelist (which id/label fields the thin SSE signal carries
— `cohort_instance_id`, and whether `sla_id`/`state`/`owner`), which query keys it invalidates, and whether to
expose the agent-runtime snapshot for a full pending-plan view. One screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. glea-service only; mirror the `cohort_events`
consumer->writer->reader->readmodel->router chain for a sibling `cohort_sla_events` table. Observability-grade,
degrading, backward-compatible — the UI's authorized read path over REST, ready for P4 to render + SSE-signal.
