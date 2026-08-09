# ADR-063 Phase 1 — cohort runtime foundation: report

**This is Phase 1 of 3.** Phases 2 (registry cohort-definition CRUD + close ingress + `open→closing→closed`
drain) and 3 (GLEA read-models + webui) are separate prompts and are **not** built here.

## 1. Outcome

The runtime foundation for **purely observational** cohorts is in and green. A pack manifest may now carry an
optional `cohort_membership`; on spawn, agent-runtime atomically opens/joins a per-`correlation_value` cohort
instance (Mongo SoR, unique index, first-writer-wins), stamps the segment's OTel root span with
`amendia.cohort.*`, drains the roster on member-terminal, and emits fail-soft `CohortLifecycleEvent`s. **Zero
execution authority**: nothing sequences, gates, hands off, or terminates any segment. A pack without a
membership, and a deployment that registers no cohort, behave exactly as before.

## 2. Contracts added

- **`CohortMembership`** (`libs/amendia_contracts/.../process_pack.py`): `{cohort_def_id, correlation_key}`
  (dotpath into the pack's own trigger); added as optional `cohort_membership: Optional[CohortMembership] = None`
  on `ProcessPackManifest`. Additive — the seed manifest still validates, absent → standalone.
- **`CohortLifecycleOp`** (`governance_events.py`): `opened | member_joined | closing | closed | late_join`
  (full vocabulary defined now; Phase 1 fires `opened`/`member_joined`/`late_join`).
- **`CohortLifecycleEvent`** (`governance_events.py`): `_service = AGENT_RUNTIME`, `_event_name =
  COHORT_LIFECYCLE`; structural/domain-neutral fields (`cohort_def_id`, `cohort_instance_id`,
  `correlation_value` (opaque), `op`, optional `process_instance_id`/`pack_key`/`detail`, `Trace`). Routing key
  `agent_runtime.cohort_lifecycle.v1`.
- **Routing constant** `COHORT_LIFECYCLE = "cohort_lifecycle"` (`libs/amendia_common/events.py`).
- **Telemetry conventions** (`libs/amendia_telemetry/.../conventions.py`): `COHORT_DEF_ID`,
  `COHORT_INSTANCE_ID`, `COHORT_CORRELATION_VALUE` in a **distinct `amendia.cohort.*` namespace** — never the
  existing `amendia.correlation_id`.

## 3. The SoR (`cohort_instances`)

- **Collection + indexes** (`app/db/mongo.py`): `COHORT_INSTANCES`, **unique on `correlation_value`** (the V1
  global-uniqueness invariant → concurrent same-value joins collapse to one row) + unique `cohort_instance_id`.
  Created at startup by `create_indexes`.
- **Model** (`app/models/cohort_instance.py`): `CohortInstance` (id, `cohort_def_id`, `correlation_value`,
  `state`, `members[]`, `active_member_count`, `opened_at/updated_at/closed_at`, `close_outcome`) +
  `CohortMember` (`process_instance_id`, `pack_key`, `terminal`) + `CohortState` enum.
- **Repo** (`app/dal/cohort_repo.py`):
  - `get_or_open` — one atomic `find_one_and_update({correlation_value}, {$setOnInsert}, upsert=True, AFTER)`,
    first-writer-wins. Creation detected by whether our candidate id survived `$setOnInsert`; a lost upsert
    race (`DuplicateKeyError`) falls back to reading the winner's row.
  - `add_member` — idempotent via a `members.process_instance_id: {$ne: pid}` guard so push + `$inc` are atomic
    **and** a re-join is a no-op (count never double-counts). Returns True only on a fresh add.
  - `mark_member_terminal` — idempotent `$elemMatch` (non-terminal only) flips `terminal` + `$inc -1`.
  - `get` / `get_by_correlation_value`.
- **State machine wired vs deferred:** `open` + member accumulation + the roster/active-count drain are wired
  now. `closing`/`closed` are **modelled** (enum, `closed_at`, `close_outcome`, `active_member_count`) but the
  transitions are **deferred to Phase 2** (no close signal exists yet).

## 4. Join-on-spawn (`DispatchService._maybe_join_cohort`)

After the instance is inserted **and accepted**, before `engine.start`, if the loaded bundle's manifest has a
`cohort_membership`:
1. Resolve `correlation_value` from the envelope via `membership.correlation_key` (dotpath). **Absent/null →
   `None` → run standalone** (graceful non-membership; debug log). — `resolve_correlation_value`.
2. `get_or_open(correlation_value, cohort_def_id)` (atomic). If it **created** the row → emit `opened`. Then
   `add_member` (idempotent) → emit `member_joined` on a fresh add; **skip the emit on a re-join**.
3. **Integrity guard:** existing cohort has a *different* `cohort_def_id` → **not re-homed** (the value is the
   unique key); the member still attaches and an anomaly `late_join` (with detail) is emitted.
4. **Closed-cohort late sibling:** cohort already `closed` → attach + `late_join`; **no second cohort** for the
   value.
5. **Backlink persisted:** `cohort_instance_id` / `cohort_def_id` / `cohort_correlation_value` set on the
   `ProcessInstance` (in-memory for the imminent `engine.start`, and via `update_fields` to Mongo for Phase 3).
- **Fail-soft everywhere:** the whole block is wrapped `try/except` and always falls through to `engine.start`.
  The service is also injected optionally (`cohort_service=None`) so existing unit tests run unchanged.

## 5. Telemetry stamp + member-terminal hook

- **Root-span stamp** (`engine.start`): factored into the pure `ProcessEngine._instance_span_attrs(instance)`
  — base `amendia.*` identity attrs plus the three `amendia.cohort.*` tags **only when the instance joined a
  cohort**. Propagates onto every re-parented node span → ClickHouse `otel_traces` (how Phase 3/GLEA groups).
  Additive; telemetry-off stays a no-op.
- **Member-terminal drain** (`engine._on_member_terminal`, called from both `_complete` and `_fail`,
  fail-soft): `CohortService.on_member_terminal` → `mark_member_terminal` (marks the member, decrements the
  active count). No member-terminal lifecycle event is emitted — member instances already publish their own
  terminal telemetry (one source of truth). The `closing→closed` transition is deferred to Phase 2; the hook is
  wired so Phase 2 only adds the close path.

## 6. Tests added (16) + the concurrency result

- `test_cohort_contracts.py` (4) — manifest round-trips **with and without** membership; event serializes with
  routing key `agent_runtime.cohort_lifecycle.v1`; the op vocabulary is complete.
- `test_cohort_repo.py` (4) — **get-or-open atomic under `asyncio.gather` of 8 → exactly one row and one
  creator**; `add_member` idempotent (no duplicate, count not doubled); `mark_member_terminal` decrements once.
- `test_cohort_service.py` (8) — the headline: **two triggers, same `correlation_value`, two different packs →
  one cohort, roster of both, `opened`×1 + `member_joined`×2**, both instances backlinked; absent key →
  standalone (no cohort, no attrs); re-dispatch (idempotent instance) → no double-join; seeded **closed cohort →
  `late_join`, not reopened**; **`cohort_def_id` mismatch → `late_join`, not re-homed**; **non-member pack →
  zero cohort rows/backlink, runs normally**; root-span attrs carry cohort tags only when joined
  (`_instance_span_attrs`).

## 7. Verification

- `agent-runtime`: `uv run --extra dev pytest` → **358 passed, 4 skipped** (+15 vs the pre-change 343).
- `process-registry`: **366 passed** — includes the regenerated OpenAPI snapshot (the shared manifest gained
  `cohort_membership`; `python scripts/dump_openapi.py` re-dumped `webui/openapi/registry.json`, a
  backend-generated artifact gated by `test_openapi_snapshot`).
- Lib-consumer regression check: `glea-service` **49 passed**, `ingestor` **20 passed** (the contract/event/
  convention additions are purely additive).
- `amendia_contracts` has no standalone suite; its Phase-1 additions are exercised via `test_cohort_contracts`
  and the consumer suites above.

## 8. Deferred / left open

- **Phase 2:** registry cohort-definition CRUD + membership assignment; close-message ingress classification;
  `cohort_close_requested` event + agent-runtime consumer; the `open→closing→closed` drain and the
  no-open-cohort / late-join end-to-end edges. (`CohortLifecycleOp.closing`/`closed` and the SoR's
  `closing`/`closed`/`close_outcome`/`active_member_count` fields are defined now, unused until then.)
- **Phase 3:** GLEA `cohort_instances` read-model, instance-read-model cohort columns, cohort list/detail read
  APIs, and the webui cohort views + instance-view backlink.
- **Frontend follow-up (not Phase 1):** `webui/openapi/registry.json` was re-dumped, so `webui`'s
  `gen:api:check` will want a `cd webui && npm run gen:api` + commit. The generated types only gain the optional
  `cohort_membership` on the manifest; no hand-written webui change is needed in this phase.
- **Invariant reminder:** V1 rests on `correlation_value` being globally unique (ADR-063 Assumptions); the
  integrity guard flags — but does not resolve — a violation.
