# ADR-064 P3 — cohort SLA GLEA surfacing: report

**This is P3 of 4** (GLEA read surface, glea-service, backend-only). P1 (definition model) + P2 (runtime +
`CohortSlaEvent`) landed. P4 (webui + the thin SSE signal) is a separate prompt — none built here. No SSE /
notification-service / webui / agent-runtime change.

## 1. Outcome

GLEA now **consumes `CohortSlaEvent`** (`agent_runtime.cohort_sla.v1`) into its **own** `cohort_sla_events`
ClickHouse table, derives the **current state per SLA** + an **owner-attributed breach rollup**, and surfaces
them on the existing cohort REST endpoints (detail `sla` section + compact list badges). A cohort with **no** SLA
events returns the same shape as before with empty SLA fields (backward-compatible). `audit_events` and
`cohort_events` are untouched; the agent-runtime Mongo state stays the SoR (this is observability-grade). glea
suite **82 passed** (+16); webui build green.

## 2. Consumer binding + `handle` branch + mapper

- `events/consumer.py`: added `rk(Service.AGENT_RUNTIME, COHORT_SLA)` (`agent_runtime.cohort_sla.v1`) to
  `AUDIT_BINDING_KEYS`. Requeue-on-outage / drop-on-poison discipline is the generic path already there.
- `main.py` `handle`: a **third** branch — `is_cohort_sla_event → cohort_sla_writer.insert(to_cohort_sla_row(...))`,
  ahead of the cohort-lifecycle and audit branches (the three cohort tables never overlap).
- `events/mapper.py`: `is_cohort_sla_event` (kind == `cohort_sla`) + `to_cohort_sla_row` (structural projection;
  requires `event_id` + `cohort_instance_id` + `sla_id` → else `UnmappableEvent`). `due_at`/`at_risk_at`/
  `detected_at` are kept as the **emitted ISO strings** ("" when absent) — lossless, parse-free.

## 3. The `cohort_sla_events` table + writer

- `clickhouse/schema.py`: `create_cohort_sla_table_ddl` + `COHORT_SLA_INSERT_COLUMNS`/`_READ_COLUMNS` +
  `cohort_sla_alter_add_columns_ddl` (empty stub). Columns: `event_id`, `occurred_at`, `ingested_at`
  (DEFAULT now64), `state` (LowCardinality), `cohort_instance_id`, `cohort_def_id`, `correlation_value`,
  `sla_id`, `kind` (LC), `ref`, `owner` (LC), `clock` (LC), `due_at`, `at_risk_at`, `detected_at` (String).
  `ENGINE = ReplacingMergeTree(ingested_at)`, `ORDER BY (cohort_instance_id, sla_id, occurred_at, event_id)`
  (so the latest state per `sla_id` is a cheap read; idempotent on `event_id` via the sort tuple), TTL on
  `occurred_at`.
- `clickhouse/client.py` `bootstrap`: `CREATE TABLE IF NOT EXISTS` the SLA table (+ its ALTER stub) alongside
  the other two — bootstraps idempotently on startup. `config.py`: `CLICKHOUSE_COHORT_SLA_TABLE =
  "cohort_sla_events"`.
- `clickhouse/writer.py`: `CohortSlaWriter` (own table; idempotent; a CH failure raises `StorageUnavailable`
  → consumer requeues, never ack-and-drop). Wired in `main.py` startup (mirrors `cohort_writer`).

## 4. Reader + the current-state / owner-rollup derivation

- `clickhouse/reader.py` (on `CohortReader`): `cohort_sla_events_for(id)` /
  `cohort_sla_events_by_correlation_value(value)` / `cohort_sla_events_all()`, reads with `FINAL` (a redelivered
  `event_id` shows once), raising `StorageUnavailable` on a CH error like the other cohort reads.
- `readmodels.py` (pure, no I/O): `current_sla_states(rows)` = the **latest event per `sla_id`** by
  `(occurred_at, event_id)` — states are monotonic (pending→at_risk→breached/satisfied/voided) so latest wins;
  `owner`/`kind`/`ref`/`clock` are stable per `sla_id`; empty time strings → `None`. `sla_summary(entries)` =
  the **owner-attributed breach rollup** `{external, amendia, shared, total}` + `at_risk`/`satisfied`/`voided`
  counts, computed over the **current** state per `sla_id`. `build_sla_section` composes them.

## 5. Endpoint / response-model additions + backward-compat

- `models/cohort.py`: `CohortSlaEntry` (`sla_id, kind, ref, owner, clock, state, due_at?, at_risk_at?,
  detected_at?`), `CohortSlaBreaches`, `CohortSlaSummary` (`states[] + breaches + at_risk/satisfied/voided`).
  `CohortDetailOut` gains `sla: CohortSlaSummary` (default-empty); `CohortListEntry` gains `sla_breaches` +
  `sla_at_risk` (compact badges).
- `readmodels.build_cohort_detail`/`build_cohort_list` gained an **optional** `sla_rows` param (default `None`)
  — so existing 2-arg callers/tests are unchanged; the detail attaches the `sla` section, the list attaches the
  two badge counts (grouped per `cohort_instance_id`).
- `routers/cohorts.py`: all three endpoints fetch the SLA rows in the same `try` and pass them in. A cohort with
  no SLA events → `cohort_sla_events_for` returns `[]` → **empty SLA section / zero badges**, otherwise the
  response is identical to today (existing consumers unaffected). Reads still **degrade to 503**, not error,
  when ClickHouse is down (same `StorageUnavailable` path).

## 6. Verification

- `cd backend/services/platform/glea-service && uv run --extra dev pytest` → **82 passed** (+16 in
  `tests/test_cohort_sla_glea.py`): binding key registered + disjoint from cohort-lifecycle; mapper maps +
  rejects missing `event_id`/`cohort_instance_id`/`sla_id` + is deterministic (dedup); schema↔insert-column
  consistency; **requeue** on `StorageUnavailable` + **drop** on `UnmappableEvent`; **current-state** (`at_risk`
  then `breached` → `breached`; `at_risk` then `satisfied` → `satisfied`); **owner rollup** (external vs amendia
  attribution); detail `sla` section + list badges; and the **backward-compat empty** shape (no SLA events).
  Existing cohort suites pass unchanged (`test_cohort_api` fake reader extended with the three no-op SLA reads).
- **OpenAPI/gen:** glea's webui types are **hand-written** (per `webui/scripts/gen-api.mjs` — glea is not in the
  generated `gen/` set; only `registry.json` has an offline snapshot, and process-registry is untouched in P3).
  The additions are additive/optional on the response, so no snapshot/gen change is needed.
- `cd webui && npm run build` (`tsc --noEmit && vite build`) → **exit 0, built in 1.77s** (the UI doesn't render
  the SLA fields until P4; the additive response is type-compatible with the existing hand-written
  `CohortDetailOut`).

## 7. Follow-ups for P4 (webui + the thin SSE signal)

- **`signal_mapper.py` whitelist (thin SSE invalidation — ids/labels only):** carry `cohort_instance_id`
  (which cohort to refetch), `cohort_def_id`, `sla_id`, `state`, and `owner`. **Do not** carry `due_at`/
  `at_risk_at`/`detected_at` or any timing content — the browser re-fetches authorized SLA data over the P3 REST
  endpoints (`GET /cohorts/{id}` → the `sla` section). Extend `_ALLOWED_FIELDS` + the `event_type` guard for
  `agent_runtime.cohort_sla.v1` (kind segment length check).
- **Query-key invalidation:** on a cohort-SLA signal, invalidate the cohort detail (`["cohort", cohort_instance_id]`)
  and the cohort list (so badges update). No new fetch endpoint needed — reuse the P3 cohort reads.
- **Full pending-plan view (optional):** GLEA shows only expectations that have *transitioned* (at_risk/breached/
  satisfied/voided) — correct for a who-was-late view. A "every expectation incl. still-`pending` with live
  countdowns" view would need the **agent-runtime snapshot** (the `cohort_sla_expectations` SoR) exposed over a
  new role-guarded REST endpoint on agent-runtime — flag as a P4 decision, not a GLEA change.
- **`sla_breaches` metric:** kept on the cohort surface (per ADR-064) — unifying it with the global `audit`
  `sla_breaches` metric is a separate, optional decision, deliberately not taken here.
- **Reviewer note:** live only after `docker compose build glea-service` (+ restart); the new table bootstraps
  idempotently on startup (`CREATE TABLE IF NOT EXISTS`).
