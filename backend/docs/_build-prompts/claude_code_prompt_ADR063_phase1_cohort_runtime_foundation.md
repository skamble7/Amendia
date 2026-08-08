# Claude Code prompt — ADR-063 Phase 1: cohort runtime foundation

Implement **Phase 1** of **ADR-063**
(`backend/docs/adr/ADR-063-cohort-observability-grouping-for-segmented-cross-system-processes.md`): the
runtime foundation for cohorts. A cohort is a **purely observational** grouping of the segment instances that
belong to one real-world case, correlated by a business key from the trigger message. **V1 has zero execution
authority** — nothing here sequences, gates, hands off state, or terminates any segment. Read the ADR first;
this prompt implements only Phase 1 (Phases 2–3 — registry CRUD + close ingress, and GLEA surfacing — are
separate prompts, do NOT build them here).

## What Phase 1 covers

Contracts + telemetry conventions; the cohort-instance system-of-record (SoR) as a persisted state machine in
agent-runtime; join-on-spawn; root-span stamping; member-terminal drain advance; and the fail-soft cohort
lifecycle event. No registry cohort-definition CRUD, no close-message ingress, no GLEA read-models/UI in this
phase — but the lifecycle **event** must be emitted so Phase 3 has data.

## Read first (grounding — confirm before you change)

- `backend/services/agent-runtime/app/services/dispatch_service.py` — `DispatchService._handle`: envelope
  fetched, `bundle` loaded, `ProcessInstance.new(...)` inserted, then `self._engine.start(instance,
  envelope_doc)`. **This is the join-on-spawn hook** (after insert, around the accept/start).
- `backend/services/agent-runtime/app/engine/engine.py` — `start()` (~line 251): opens the instance ROOT span
  via `start_instance_trace(..., attrs={CORRELATION_ID, PROCESS_INSTANCE_ID, PACK_KEY, PACK_VERSION})`. **This
  is the telemetry-stamp hook.** Also find the terminal-emit path (the instance reaching
  completed/failed/cancelled — around the `_otel_trace_id` / dispatch-terminal emits, ~lines 660–820) — that
  is the **member-terminal** hook.
- `backend/services/agent-runtime/app/models/process_instance.py` — `ProcessInstance` (+ `.new`). Note it
  already has a `correlation_id` (OTel/trace correlation, defaults to `trigger_id`) — the cohort
  `correlation_value` is a **DIFFERENT** concept; do not conflate them.
- `libs/amendia_contracts/amendia_contracts/process_pack.py` — the manifest (`TriggerSource` shows the dotpath
  style to mirror for `correlation_key`).
- `libs/amendia_contracts/amendia_contracts/governance_events.py` — `PackLifecycleEvent` / `PackLifecycleOp`
  and the `EventBase` + `Trace` shape to mirror for `CohortLifecycleEvent`.
- `backend/services/process-registry/app/events/publisher.py` — `emit_pack_lifecycle` (the **fail-soft**
  publisher pattern to mirror in agent-runtime).
- `libs/amendia_common/events.py` (routing-name constants like `PACK_LIFECYCLE`) and
  `libs/amendia_telemetry/amendia_telemetry/conventions.py` (`CORRELATION_ID`, `PROCESS_INSTANCE_ID`,
  `PACK_KEY`).
- `backend/services/agent-runtime/app/db/mongo.py` + an existing repo (e.g. `dal/instance_repo.py`) for the
  collection/index + repo conventions, and `main.py` for startup index creation / DI wiring.

## Tasks

### 1. Contracts

1a. **`CohortMembership` on the manifest** (`process_pack.py`): a new `ContractModel` with `cohort_def_id: str`
and `correlation_key: str` (a dotpath into the pack's own trigger envelope). Add it as an **optional** field
`cohort_membership: Optional[CohortMembership] = None` on the pack manifest. A pack without it is a normal
standalone process — nothing else changes. (V1: at most one membership per pack.)

1b. **`CohortLifecycleEvent` + `CohortLifecycleOp`** (`governance_events.py`), sibling of `PackLifecycleEvent`,
`_service = Service.AGENT_RUNTIME`. Ops: `opened`, `member_joined`, `closing`, `closed`, `late_join`. Fields
must stay **structural / domain-neutral** (ADR-058 review gate): `cohort_def_id: str`, `cohort_instance_id:
str`, `correlation_value: str` (opaque data), plus per-op detail where useful (`process_instance_id`,
`pack_key` on `member_joined`; a short `detail`/anomaly string on `late_join`) and a `Trace`. Add the routing
constant (e.g. `COHORT_LIFECYCLE`) in `amendia_common/events.py` and wire `_event_name`.

Phase 1 emits `opened`, `member_joined`, and `late_join`. (`closing`/`closed` are emitted in Phase 2 when the
close ingress lands — define the ops now so the contract is complete, but it is fine if only open/join/late
fire in this phase.)

### 2. Telemetry conventions

Add to `amendia_telemetry/conventions.py`: `COHORT_DEF_ID = "amendia.cohort.def_id"`, `COHORT_INSTANCE_ID =
"amendia.cohort.instance_id"`, `COHORT_CORRELATION_VALUE = "amendia.cohort.correlation_value"`. (Distinct
`amendia.cohort.*` namespace — do NOT reuse the existing `amendia.correlation_id`.)

### 3. Cohort-instance SoR + state machine (agent-runtime)

3a. **Model** — a runtime aggregate `CohortInstance` (agent-runtime `app/models`, alongside
`process_instance.py`): `cohort_instance_id` (e.g. `coh-<hex>`), `cohort_def_id`, `correlation_value`, `state`
(`open` | `closing` | `closed`), a member roster (list of `{process_instance_id, pack_key}`), an
`active_member_count` (or derive from member terminal-status), `opened_at`/`updated_at`/`closed_at`,
`close_outcome: Optional[str]`. **State machine transitions only:** `open → closing`, `open → closed`, `closing
→ closed`. (`closing`/`closed` land fully in Phase 2; model them now.)

3b. **Collection + repo** — a `cohort_instances` collection with a **UNIQUE index on `correlation_value`**
(create it at startup like the other indexes). `CohortInstanceRepository` with an **atomic get-or-create**:
`find_one_and_update({correlation_value}, {$setOnInsert: {...open...}}, upsert=True,
return_document=AFTER)` — first-writer-wins, no check-then-insert. Provide: `get_by_correlation_value`,
`get_or_open(...)`, an **idempotent** `add_member(cohort_instance_id, process_instance_id, pack_key)` (a
`$addToSet` on the roster keyed so a re-join is a no-op), and a `mark_member_terminal(...)` /
`decrement_active(...)` used later by the drain.

3c. **`CohortService`** (agent-runtime `app/services`): `join_on_spawn(instance, membership, envelope)` and
`on_member_terminal(instance)`. Keep it thin; it wraps the repo + the lifecycle emit.

### 4. Join-on-spawn (`DispatchService._handle`)

After the instance is inserted (and accepted), if the loaded `bundle`'s manifest has a `cohort_membership`:

1. Resolve `correlation_value` from `envelope_doc` via `membership.correlation_key` (dotpath). If the field is
   **absent/null**, do NOT join — the segment runs as a normal standalone process (graceful non-membership).
   Log at debug and continue.
2. `get_or_open(correlation_value, cohort_def_id)` — atomic. If it **created** the row, emit `opened`. Always
   then `add_member(...)` (idempotent) and emit `member_joined` (skip the emit if the member was already in the
   roster — re-spawn/idempotent path).
3. **Integrity guard:** if an existing cohort for that `correlation_value` has a **different** `cohort_def_id`
   than this membership declares, do NOT re-home it — log a warning and emit `late_join` (anomaly detail). Still
   let the segment run.
4. **Closed-cohort late sibling:** if the cohort is already `closed`, attach the member to the existing closed
   cohort and emit `late_join` (do NOT open a second cohort for the same value).
5. Persist `cohort_instance_id` onto the `ProcessInstance` (add an optional `cohort_instance_id: Optional[str]
   = None` field + a repo update, or set it at create) so Phase 3 has the backlink and step 5 below can stamp
   it.

**Fail-soft:** a cohort-join failure must **never** break dispatch/execution of the segment itself — wrap in
try/except, log, continue to `engine.start`. The segment is the product; the cohort is observation.

### 5. Root-span stamping (`engine.start`)

If the instance has a `cohort_instance_id`, add to the `start_instance_trace(attrs={...})` dict:
`COHORT_DEF_ID`, `COHORT_INSTANCE_ID`, `COHORT_CORRELATION_VALUE`. This propagates onto every node span (they
re-parent to the root) → ClickHouse `otel_traces`, which is how Phase 3/GLEA groups. Additive and side-effect
free when there is no cohort (attrs simply omitted); telemetry-off stays a no-op exactly as today.

### 6. Member-terminal drain hook

At the instance terminal-emit path in `engine.py` (completed/failed/cancelled), call
`CohortService.on_member_terminal(instance)` (fail-soft). For Phase 1 it decrements the active count / marks the
member terminal in the roster; the actual `closing → closed` transition is exercised in Phase 2 (no close
signal exists yet), but wire the hook now so Phase 2 only adds the close path. Do not emit a member-terminal
lifecycle event (member instances already publish their own terminal telemetry — one source of truth).

### 7. DI / startup wiring

Wire `CohortInstanceRepository` + `CohortService` through `deps.py`/`main.py` like the sibling
repos/services, and create the unique index at startup. A fail-soft cohort publisher helper (e.g.
`emit_cohort_lifecycle` in agent-runtime `events/publisher.py`) mirroring `emit_pack_lifecycle`.

## Tests

- **Unit (contracts):** manifest round-trips with and without `cohort_membership`; `CohortLifecycleEvent`
  serializes with a valid routing key; a manifest with membership still validates.
- **Unit (repo):** `get_or_open` is atomic and idempotent — two concurrent `get_or_open` for the same
  `correlation_value` yield **one** row (simulate with `asyncio.gather`); `add_member` is idempotent (re-add =
  no duplicate roster entry).
- **Service/e2e (the headline):** dispatch two triggers with the **same** `correlation_value` that triage to
  **two different member packs** of the same cohort → exactly **one** cohort instance, roster has both members,
  `opened` emitted once + `member_joined` twice. A trigger whose `correlation_key` field is absent → runs, no
  cohort. A re-dispatch of the same trigger (idempotent instance) does not double-join. Membership pointing at a
  cohort already `closed` (seed one) → `late_join`, no second cohort.
- Confirm a **non-member** pack (no `cohort_membership`) dispatches and runs exactly as before (no cohort rows,
  no cohort attrs on its spans).

## Do not

- Do not build registry cohort-definition CRUD, membership-assignment UI, close-message ingress, the
  `cohort_close_requested` event/consumer, or any GLEA read-model/webui view — those are Phases 2–3.
- Do not give the cohort any execution authority (no sequencing/gating/termination of segments).
- Do not conflate the cohort `correlation_value` with the existing instance `correlation_id`.
- Do not let a cohort failure break segment dispatch/execution (fail-soft everywhere).
- Do not touch ADR-059/060/061/062 behaviour, HITL gating, or the type-compat guard.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- A pack manifest optionally carries `cohort_membership`; packs without it are unchanged.
- Two same-`correlation_value` segments across two packs share exactly one persisted `cohort_instance`
  (unique-index + atomic get-or-create proven under concurrency); roster + `opened`/`member_joined` events
  correct; absent-key → graceful non-membership; closed-cohort → `late_join`.
- Each member segment's OTel spans carry `amendia.cohort.*` attributes; non-member spans do not.
- Member-terminal hook wired (drain-ready for Phase 2). Cohort lifecycle events emit fail-soft.
- `pytest` green for `agent-runtime`, `amendia_contracts`, and any touched lib; existing suites unaffected.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR063_phase1_cohort_runtime_foundation_report.md`
(uncommitted): (1) outcome one-liner; (2) contracts added (`CohortMembership`, `CohortLifecycleEvent`/ops,
routing const, telemetry conventions); (3) the SoR — collection/index, atomic get-or-create, state-machine
states wired vs deferred to Phase 2; (4) the join-on-spawn hook + fail-soft behaviour + the graceful-non-member
and late-join branches; (5) the telemetry stamp + member-terminal hook; (6) tests added and the concurrency-dedup
result; (7) verification commands + results; (8) anything deferred to Phase 2/3 or left open. Keep it to a
screen, and state clearly that this is **Phase 1 of 3** so the ADR phase plan can be tracked.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Prefer the fix at the right layer over a shim. Stay
inside the Amendia repo and the Phase-1 scope above.
