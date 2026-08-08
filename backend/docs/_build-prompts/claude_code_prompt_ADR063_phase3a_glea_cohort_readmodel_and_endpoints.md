# Claude Code prompt — ADR-063 Phase 3A: GLEA cohort read-model + cohort read APIs (backend for the UX)

Implement **Phase 3A** of **ADR-063** — the **backend read side** that the cohort UI (Phase 3B, webui) will
render against. Build this first so the frontend always has real endpoints. **No webui in this phase.**

Context: Phases 1–2 landed the runtime — cohort SoR + state machine, join-on-spawn, the
`CohortLifecycleEvent` stream (`opened|member_joined|closing|closed|late_join`, routing
`agent_runtime.cohort_lifecycle.v1`), cohort-definition CRUD, membership assignment, and the close ingress.
**But GLEA does not consume the cohort events at all** — they're emitted and dropped, and there is no way to
read a cohort back. Phase 3A fixes that: GLEA consumes the stream into a cohort read-model and serves
`GET /cohorts` + `GET /cohorts/{id}`, plus two small adjuncts the UI needs (instance backlink fields; a pack's
trigger field names for the membership picker).

Design stance (decided): **GLEA-centric read.** The cohort views are served from GLEA's event-sourced
read-model (consistent with how ADR-058 built the instance view), not by putting agent-runtime on the read
path. The agent-runtime Mongo cohort SoR remains the **authoritative** runtime state; GLEA's view is
observability-grade, derived from the (fail-soft) event stream — note that caveat in the report.

## Read first (the exact seams)

- `backend/services/platform/glea-service/app/events/consumer.py` — `AUDIT_BINDING_KEYS` (add the cohort key
  here) and the ack discipline (`StorageUnavailable` → requeue, else drop).
- `backend/services/platform/glea-service/app/events/mapper.py` — maps `(routing_key, payload)` → a row. Add
  the cohort branch.
- `backend/services/platform/glea-service/app/main.py` — the `handle(routing_key, payload)` wiring +
  `AuditWriter`/`AuditReader` bootstrap. You'll branch the handler and add a cohort writer/reader.
- `backend/services/platform/glea-service/app/clickhouse/schema.py` — `audit_events` DDL, `INSERT_COLUMNS`,
  and `alter_add_columns_ddl` (the idempotent-migration pattern). Mirror this for the new cohort table.
- `backend/services/platform/glea-service/app/clickhouse/writer.py` + `reader.py` — the writer/reader
  patterns (borrowed-client inserts, `FINAL` reads).
- `backend/services/platform/glea-service/app/readmodels.py` — pure row→shape functions (add cohort builders).
- `backend/services/platform/glea-service/app/routers/audit.py` + `app/models/audit.py` — endpoint + response
  model patterns to mirror in a new `routers/cohorts.py` + `models/cohort.py`.
- `libs/amendia_contracts/amendia_contracts/governance_events.py` — `CohortLifecycleEvent` (touch-ups below);
  `libs/amendia_common/events.py` — the `COHORT_LIFECYCLE` routing const + `rk(...)`.
- `backend/services/agent-runtime/app/services/cohort_service.py` — the emit sites (update for the new fields).
- `backend/services/agent-runtime/app/routers/instances.py` — the `GET /instances/{id}` dict (add cohort
  fields, ~lines 42–56).
- `backend/services/process-registry/app/routers/packs.py` + the trigger-schema helper
  (`flatten_schema_fields` / the onboarding field-picker code) — for the pack trigger-fields endpoint.

## Tasks

### 1. Contract touch-ups (so the read-model reads clean fields, not free text)

On `CohortLifecycleEvent` add two optional, structural fields and populate them at the emit sites:
- `close_outcome: Optional[str] = None` — set on `closing`/`closed` (today the outcome is stuffed into the
  free-text `detail`; make it a first-class field; keep `detail` too).
- `pack_version: Optional[str] = None` — set alongside `pack_key` on `member_joined` (the roster needs the
  exact version so Phase 3B can fetch the right BPMN). `instance.pack_version` is available at the emit site.

Update `CohortService` emits accordingly. Additive/optional — Phases 1–2 tests must stay green.

### 2. GLEA ingest — consume the cohort stream into a dedicated read-model table

2a. Add `rk(Service.AGENT_RUNTIME, COHORT_LIFECYCLE)` to `AUDIT_BINDING_KEYS`.

2b. A **dedicated ClickHouse table `cohort_events`** (do NOT overload `audit_events` — it's sorted by
`correlation_id` and has no cohort columns; cohort reads query by `cohort_instance_id`). Follow `schema.py`:
`ReplacingMergeTree(ingested_at)` ordered by `(cohort_instance_id, occurred_at, event_id)`, idempotent on
`event_id`. Columns (all structural): `event_id, occurred_at, op, cohort_instance_id, cohort_def_id,
correlation_value, member_process_instance_id, member_pack_key, member_pack_version, member_correlation_id,
close_outcome, detail, trace_id`. Add its DDL to the bootstrap + an idempotent `alter_add_columns_ddl`
sibling. Keep `audit_events` untouched.

2c. `mapper.py`: a cohort branch mapping a `CohortLifecycleEvent` payload → a `cohort_events` row.
`member_*` come from the event's `process_instance_id`/`pack_key`/`pack_version` and its `trace.correlation_id`
(the member instance's correlation_id — the join key to `audit_events`; empty on `opened`/`closing`/`closed`).

2d. `main.py` `handle`: branch by routing key — cohort key → a new `CohortWriter.insert(row)`; everything else
→ the existing audit writer. Same `StorageUnavailable`→requeue discipline (cohort events must not be dropped on
a ClickHouse blip either).

### 3. Read-model builders (pure functions, `readmodels.py`)

Given cohort rows + member-outcome rows, build the two shapes:
- `build_cohort_list(cohort_rows, member_outcome_rows)` → one entry per `cohort_instance_id`: `cohort_def_id`,
  `correlation_value`, `state` (from the latest of `opened`/`closing`/`closed`), `member_count` (distinct
  `member_process_instance_id` from `member_joined`), a **rollup** `{done, running, failed}` (join each
  member's `member_correlation_id` to its terminal outcome — `PROCESS_COMPLETED`→done,
  `PROCESS_FAILED`→failed, no terminal→running), `opened_at`, `closed_at`, `outcome` (`close_outcome`), and
  `anomalies` (count of `late_join`).
- `build_cohort_detail(cohort_rows_for_one, member_outcome_rows)` → identity + a **roster** (per member:
  `process_instance_id`, `pack_key`, `pack_version`, `correlation_id`, `status` done/running/failed,
  `started_at`, `ended_at`, `outcome`) + the **lifecycle event stream** (ordered ops with timestamps + detail)
  + **close** (signalled?, `outcome`, current `state`, late-join flags).

Member status/duration derive from `audit_events`: `DISPATCH_ACCEPTED` (created/started) and
`PROCESS_COMPLETED`/`PROCESS_FAILED` (terminal + outcome), looked up by the members' `correlation_id`s. A
member with no terminal row = `running`. Keep these functions I/O-free (rows in → shape out) like the existing
builders.

### 4. Reader queries + router + models

4a. `reader.py`: `cohort_events_all()` (list), `cohort_events_for(cohort_instance_id)`, and a member-outcome
fetch by a set of `correlation_id`s (reuse the existing audit read where possible). Reads use `FINAL`.

4b. `routers/cohorts.py` (+ `models/cohort.py` response models), mounted like `audit.py`, principal-guarded:
- `GET /cohorts` → the list (support an optional `state` filter and a sensible default ordering, newest first).
- `GET /cohorts/{cohort_instance_id}` → the detail.
- `GET /cohorts/by-correlation/{correlation_value}` → detail resolved by the business key (handy since
  `correlation_value` is the external handle). 404 when unknown.

### 5. Adjunct — instance backlink fields (agent-runtime)

`GET /instances/{process_instance_id}` currently returns a hand-built dict (with `actor_log`). Add
`cohort_instance_id`, `cohort_def_id`, `cohort_correlation_value` from the `ProcessInstance` (already persisted
in Phase 1; `None` for a standalone instance). This is what lets Phase 3B render the backlink banner. (The
list endpoint already serializes them via `ProcessInstance`.)

### 6. Adjunct — pack trigger fields for the membership picker (registry)

Expose the declared trigger schema's field paths for an active pack version, so the picker's per-pack
correlation-key dropdown can be populated. Prefer a small `GET /packs/{pack_key}/{version}/trigger-fields` →
`{fields: ["exception_id", "payment.creditor", ...]}` reusing the existing schema-flatten helper
(`flatten_schema_fields` / the onboarding field-picker path). If the pack declares no trigger schema, return
the empty list (the UI then lets the operator type a dotpath).

## Tests

- **Contract:** `CohortLifecycleEvent` round-trips with `close_outcome`/`pack_version`; existing Phase 1/2
  cohort tests still green.
- **GLEA ingest:** a `member_joined`/`opened`/`closed` payload maps to a `cohort_events` row; redelivery
  (same `event_id`) dedupes under `FINAL`; a ClickHouse failure requeues (not drops).
- **Read-model (pure, no store):** `build_cohort_list`/`build_cohort_detail` over hand-built rows produce the
  right state, member_count, rollup (a cohort with one completed + one failed + one running member → `{1,1,1}`),
  outcome, and ordered event stream. A `late_join` shows in anomalies.
- **Endpoints:** `GET /cohorts` and `GET /cohorts/{id}` and `.../by-correlation/{value}` return the shapes;
  unknown id/value → 404.
- **Adjuncts:** `GET /instances/{id}` includes the three cohort fields (present when joined, null when
  standalone); `GET /packs/{key}/{ver}/trigger-fields` returns the declared fields (and `[]` for no-trigger).
- Regression: `glea` existing audit suites unaffected (audit_events untouched); `agent-runtime`,
  `process-registry`, `amendia_contracts` green.

## Do not

- No webui — that is Phase 3B. Phase 3A ends at HTTP endpoints returning JSON.
- Do NOT modify `audit_events` schema/semantics or the sealing pass; the cohort read-model is its own table.
- Do NOT put agent-runtime on the cohort read path (GLEA serves the views); do NOT give the cohort execution
  authority; do NOT change the close/drain logic.
- Do NOT touch ADR-059/060/061/062 behaviour, HITL gating, or the type-compat guard.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- With agent-runtime emitting cohort events, GLEA persists them to `cohort_events`, and `GET /cohorts` /
  `GET /cohorts/{id}` / `.../by-correlation/{value}` return list + detail with a correct member rollup
  (done/running/failed joined from member instance outcomes), lifecycle stream, and close/outcome.
- `GET /instances/{id}` carries the cohort backlink fields; `GET /packs/{key}/{ver}/trigger-fields` serves the
  picker.
- Cohort events are never dropped on a ClickHouse outage (requeue); redelivery is idempotent.
- `pytest` green across `glea-service`, `agent-runtime`, `process-registry`, `amendia_contracts`; existing
  suites unaffected. Regenerate any OpenAPI snapshot the new routes touch.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR063_phase3a_glea_cohort_readmodel_and_endpoints_report.md`
(uncommitted): (1) outcome one-liner; (2) contract touch-ups; (3) GLEA ingest — binding key, `cohort_events`
table, mapper branch, handler split, requeue behaviour; (4) the read-model builders + how the member rollup is
joined (and the **fail-soft/observability-grade caveat** vs the authoritative agent-runtime SoR); (5) the two
adjuncts; (6) the endpoint shapes (so Phase 3B can code against them — include an example JSON for
`GET /cohorts/{id}`); (7) verification commands + results; (8) anything deferred to 3B or left open. State this
is **Phase 3A of the Phase-3 split (3A backend read → 3B webui)**. Keep it tight.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Prefer the fix at the right layer over a shim. Stay
inside the Phase-3A scope (GLEA read side + the two adjuncts); the webui is the next prompt.
