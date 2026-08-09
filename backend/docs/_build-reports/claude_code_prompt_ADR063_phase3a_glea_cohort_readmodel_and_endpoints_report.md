# ADR-063 Phase 3A — GLEA cohort read-model + cohort read APIs: report

**This is Phase 3A of the Phase-3 split (3A backend read → 3B webui).** No webui here — Phase 3A ends at HTTP
endpoints returning JSON. Phase 3B (the cohort views) is the next prompt and codes against these shapes.

## 1. Outcome

GLEA now **consumes** the cohort event stream (previously emitted and dropped) into a dedicated
`cohort_events` ClickHouse read-model and serves `GET /cohorts`, `GET /cohorts/{id}`, and
`GET /cohorts/by-correlation/{value}` — list + detail with a member rollup (done/running/failed joined from the
members' own instance outcomes), the lifecycle stream, and close/outcome. Plus the two UI adjuncts: instance
cohort-backlink fields and a pack trigger-fields picker endpoint. `audit_events` is untouched.

## 2. Contract touch-ups

`CohortLifecycleEvent` gained two optional, structural fields (additive — Phase 1/2 stay green):
`pack_version` (set alongside `pack_key` on `member_joined`/`late_join`, so the roster can fetch the right
BPMN) and `close_outcome` (a first-class field on `closing`/`closed`; `detail` is still set too). `CohortService`
emits + the `emit_cohort_lifecycle` helper were updated to populate both.

## 3. GLEA ingest

- **Binding key:** `rk(Service.AGENT_RUNTIME, COHORT_LIFECYCLE)` (`agent_runtime.cohort_lifecycle.v1`) added to
  `AUDIT_BINDING_KEYS`.
- **`cohort_events` table** (its own table — `audit_events` is sorted by `correlation_id` and has no cohort
  columns): `ReplacingMergeTree(ingested_at)` ordered by `(cohort_instance_id, occurred_at, event_id)`,
  idempotent on `event_id`; columns `event_id, occurred_at, op, cohort_instance_id, cohort_def_id,
  correlation_value, member_process_instance_id, member_pack_key, member_pack_version, member_correlation_id,
  close_outcome, detail, trace_id` + `ingested_at`. DDL added to the bootstrap (`client.bootstrap`) with an
  idempotent `cohort_alter_add_columns_ddl` sibling. `audit_events` DDL/semantics unchanged.
- **Mapper branch:** `to_cohort_row(routing_key, payload)` projects a `CohortLifecycleEvent` → a `cohort_events`
  row; `member_*` come from the event's `process_instance_id`/`pack_key`/`pack_version` and its
  `trace.correlation_id` (the member's correlation_id — the join key into `audit_events`; empty on
  `opened`/`closing`/`closed`). Missing `event_id`/`cohort_instance_id` → `UnmappableEvent` (dropped).
- **Handler split:** `main.handle` branches by `is_cohort_event(routing_key)` — cohort → `CohortWriter.insert`,
  everything else → the existing `AuditWriter`. **Same requeue discipline:** a `CohortWriter` insert failure
  raises `StorageUnavailable` → the consumer `nack(requeue=True)`, so cohort events are never dropped on a
  ClickHouse blip; redelivery dedupes on `event_id` under `FINAL`.

## 4. Read-model builders (pure, `readmodels.py`) + the rollup join

`build_cohort_list(cohort_rows, member_outcome_rows)` and `build_cohort_detail(cohort_rows_for_one, member_outcome_rows)`
are I/O-free (rows in → shape out). **The member rollup is joined**: each member's `member_correlation_id`
indexes into the members' own `audit_events` rows (`dispatch_accepted` = started; `process_completed` = done +
outcome; `process_failed` = failed; no terminal = running), tallied into `{done, running, failed}`. `state` is
the latest of `opened`/`closing`/`closed`; `member_count` = distinct `member_joined` members; `anomalies` =
`late_join` count; roster (detail) = `member_joined ∪ late_join` with a `late` flag.

**Fail-soft / observability-grade caveat:** this view is derived from the **fail-soft** `CohortLifecycleEvent`
stream, not the authoritative agent-runtime Mongo cohort SoR. A dropped/late event only degrades this view; the
runtime state stays correct. Member outcomes come from the members' own terminal telemetry (one source of
truth), not re-emitted by the cohort. This caveat is documented in `readmodels.py` and `routers/cohorts.py`.

## 5. Adjuncts

- **Instance backlink** (`agent-runtime` `GET /instances/{id}`): now returns top-level `cohort_instance_id`,
  `cohort_def_id`, `cohort_correlation_value` (from the `ProcessInstance`, persisted since Phase 1; `null` for a
  standalone instance) — the backlink banner's data.
- **Pack trigger-fields** (`registry` `GET /packs/{key}/{ver}/trigger-fields` → `{"fields": [...]}`): flattens
  the declared trigger artifact schema's field dotpaths (reusing `flatten_schema_fields`, highest owned version)
  for the membership picker's per-pack correlation-key dropdown. `[]` when the pack declares no trigger.

## 6. Endpoint shapes (for Phase 3B)

- `GET /cohorts?state=open|closing|closed` → `{count, cohorts: [CohortListEntry]}` (newest opened first).
- `GET /cohorts/{cohort_instance_id}` and `GET /cohorts/by-correlation/{correlation_value}` → `CohortDetailOut`
  (404 on unknown). Example `GET /cohorts/coh-1`:

```json
{
  "cohort_instance_id": "coh-1",
  "cohort_def_id": "wire_transfer_cohort",
  "correlation_value": "1v23p",
  "state": "closed",
  "member_count": 3,
  "rollup": { "done": 1, "running": 1, "failed": 1 },
  "opened_at": "2026-08-08T12:00:00Z",
  "closed_at": "2026-08-08T12:00:30Z",
  "outcome": "process_ended",
  "anomalies": 1,
  "roster": [
    { "process_instance_id": "pi-a", "pack_key": "wire-repair-standard", "pack_version": "1.0.0",
      "correlation_id": "cid-a", "status": "done", "started_at": "2026-08-08T12:00:01Z",
      "ended_at": "2026-08-08T12:00:20Z", "outcome": "End_Resolved", "late": false },
    { "process_instance_id": "pi-late", "pack_key": "wire-repair-standard", "pack_version": "2.0.0",
      "correlation_id": "cid-late", "status": "running", "started_at": null, "ended_at": null,
      "outcome": null, "late": true }
  ],
  "events": [
    { "op": "opened", "at": "2026-08-08T12:00:00Z", "process_instance_id": null, "detail": null },
    { "op": "member_joined", "at": "2026-08-08T12:00:01Z", "process_instance_id": "pi-a", "detail": null },
    { "op": "late_join", "at": "2026-08-08T12:00:05Z", "process_instance_id": "pi-late",
      "detail": "member joined after cohort was closed" },
    { "op": "closed", "at": "2026-08-08T12:00:30Z", "process_instance_id": null, "detail": null }
  ],
  "close": { "signalled": true, "outcome": "process_ended", "state": "closed", "late_joins": 1 }
}
```

Instance adjunct: `GET /instances/{id}` → `{ …, "cohort_instance_id": "coh-1", "cohort_def_id":
"wire_transfer_cohort", "cohort_correlation_value": "1v23p", … }` (all `null` when standalone).
Picker adjunct: `GET /packs/{key}/{ver}/trigger-fields` → `{"fields": ["exception_id", "payment.creditor", …]}`.

## 7. Verification

- `glea-service`: `uv run --extra dev pytest` → **66 passed** (+17: read-model builders, ingest/mapper/dedup/
  requeue, endpoints). Existing audit suites + `test_schema_consistency` (audit_events) unaffected.
- `agent-runtime`: **368 passed, 4 skipped** (+4: contract `close_outcome`/`pack_version` round-trip, instance
  backlink present/null; Phase-1/2 cohort suites green after adding `pack_version` to the emit).
- `process-registry`: **378 passed** (+3 trigger-fields adjunct) — includes the regenerated OpenAPI snapshot
  (new `/packs/{k}/{v}/trigger-fields` + the Phase-2 cohort routes; `python scripts/dump_openapi.py`).
- `ingestor` **23**, lib consumers `stub` **39** / `notification-service` **18** — all passed (contract change
  additive). `amendia_contracts` additions exercised via the service suites.
- Only `webui/openapi/registry.json` is a committed snapshot; glea/agent-runtime have none.

## 8. Deferred to 3B / left open

- **Phase 3B (webui):** the cohort **list** view, cohort **detail** (roster links to each member's instance
  view, consolidated timeline, close event), and the **instance-view backlink banner** — all code against the
  shapes in §6. Plus wiring the membership picker to `/packs/{k}/{v}/trigger-fields`.
- **Frontend regen:** `webui/openapi/registry.json` was re-dumped → `cd webui && npm run gen:api` + commit is
  the natural follow-up. GLEA has no committed OpenAPI snapshot; Phase 3B can add a `glea.json` if it wants
  generated types for the cohort endpoints.
- **Observability-grade view** (see §4): the cohort read-model trails the authoritative runtime SoR under event
  loss/lateness — acceptable per the ADR; if 3B needs strict consistency for a specific field it should read the
  runtime instance directly (backlink) rather than the cohort view.
