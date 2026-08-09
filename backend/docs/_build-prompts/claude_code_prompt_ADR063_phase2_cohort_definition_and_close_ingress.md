# Claude Code prompt — ADR-063 Phase 2: cohort definition registration + close ingress + drain

Implement **Phase 2** of **ADR-063**
(`backend/docs/adr/ADR-063-cohort-observability-grouping-for-segmented-cross-system-processes.md`). Phase 1
(runtime foundation — membership contract, cohort SoR state machine, join-on-spawn, telemetry stamping,
`opened`/`member_joined`/`late_join` events, and the member-terminal drain hook) is landed and green. Phase 2
adds: **cohort-definition registration** (registry), **membership assignment**, the **close-message ingress**
(recognise the external end-of-process signal and route it), and the **`open → closing → closed` drain**
end-to-end. **GLEA read-models + webui remain Phase 3 — do NOT build them here.**

The cohort stays **purely observational / zero execution authority**: close never terminates a running segment;
it waits for in-flight members to finish (`closing`), then goes `closed`.

## Read first (grounding — these are the exact seams)

- `backend/services/agent-runtime/app/dal/cohort_repo.py`, `app/services/cohort_service.py`,
  `app/models/cohort_instance.py` — the Phase-1 SoR + state machine. `active_member_count` is maintained
  atomically (add_member `$inc +1`, mark_member_terminal `$inc -1`); `CohortState` has `OPEN|CLOSING|CLOSED`;
  `on_member_terminal` already drains — Phase 2 makes it **finalize** `closing → closed`.
- `backend/services/agent-runtime/app/events/consumer.py` — `DispatchConsumer` binds ONE durable queue to
  `ingestor.trigger_dispatched.v1` (`BINDING_KEY`) and hands `(payload, routing_key)` to a handler. Phase 2
  adds a **sibling close-consumer** bound to `ingestor.cohort_close_requested.v1` (generalise `BINDING_KEY` to
  a constructor arg, or add a small `CohortCloseConsumer` — keep it minimal, same reconnect/ack discipline).
- `backend/services/agent-runtime/app/main.py` — dispatch consumer + `cohort_service` wiring (lines ~127–152);
  add the close consumer + its handler the same way.
- `backend/services/ingestor/app/services/ingestion_service.py` — `_resolve_and_dispatch`: calls
  `self._registry.resolve(envelope)`, then on match publishes `TriggerDispatchedEvent`; `RegistryNoMatch` →
  `mark_no_process`. **This is where the close branch goes.**
- `backend/services/ingestor/app/clients/registry_client.py` — `resolve(...)` + `RegistryNoMatch`/
  `RegistryUnavailable`. The classification result comes back through here.
- `backend/services/process-registry/app/services/resolver.py` + `app/routers/resolve.py` — the triage
  `/resolve` endpoint. **Fold close-classification into this single call** (below) so the ingestor makes no
  extra per-trigger round-trip.
- `backend/services/process-registry/app/dal/pack_repo.py`, `app/routers/packs.py`,
  `app/db/mongo.py` (indexes), `app/deps.py` — repo/router/index/DI patterns to mirror for the cohort
  definition + membership endpoints. `emit_pack_lifecycle`/resolver-cache `invalidate()` patterns.
- `libs/amendia_contracts/amendia_contracts/dispatch.py` (`TriggerDispatchedEvent`, `Trace`, `EventBase`
  shape) and `libs/amendia_common/events.py` (routing-name consts + `Service`/`Version`) — mirror for
  `CohortCloseRequested`.

## Tasks

### 1. Contracts — the close event

1a. `CohortCloseRequested` (in `amendia_contracts` — `dispatch.py` sibling or a new `cohort_events.py`),
`EventBase`, `_service = Service.INGESTOR`, `_event_name = COHORT_CLOSE_REQUESTED` (new const in
`amendia_common/events.py`, `Version.V1`). Fields — **structural / domain-neutral**: `correlation_value: str`
(the sole handle — see the invariant), `close_outcome: Optional[str] = None`, `cohort_def_id: Optional[str] =
None` (informational, for logging/validation only — never required to resolve), and a `Trace`. Routing key via
`EventBase.routing_key()` → `ingestor.cohort_close_requested.v1`.

### 2. Registry — cohort definition + membership

2a. **`CohortDefinition` model + `cohort_definitions` collection + repo** (`app/models/cohort.py`,
`app/dal/cohort_def_repo.py`, index in `db/mongo.py`): `cohort_def_id: str` (**unique index**),
`display_name`/`description` (optional), `close_schema: dict` (the JSON Schema of the external end-of-process
message), `close_correlation_path: str` (dotpath into a close message → the `correlation_value`), and
`close_outcome_path: Optional[str]` (dotpath → an overall outcome, if the orchestrator sends one). CRUD repo
(create/get/list/delete). Validate `close_schema` is a well-formed JSON Schema at register time.

2b. **Router** (`app/routers/cohort.py`, wired in `main.py`/`deps.py`): `POST /cohort/definitions` (register),
`GET /cohort/definitions`, `GET /cohort/definitions/{cohort_def_id}`, `DELETE
/cohort/definitions/{cohort_def_id}`. Reads require an authenticated principal like the other registry routers.

2c. **Membership assignment**: `PUT /packs/{pack_key}/{version}/cohort-membership` (set) and `DELETE` (clear).
Set validates that `cohort_def_id` exists and that `correlation_key` is a non-empty dotpath, then stamps the
pack version's stored manifest `cohort_membership` **in place** (it is additive *observational* metadata that
does not change execution, so it does NOT require a new pack version — but say so explicitly in the report;
if the team wants membership to be version-immutable, flag it rather than deciding silently). Invalidate the
resolver cache after a write (membership doesn't affect triage, but keep the pattern consistent).

### 3. Registry — fold close-classification into `/resolve`

3a. A small `CohortClassifier` (service) that, given an envelope, validates it against every registered
`close_schema` and, on a match, extracts `correlation_value` (via `close_correlation_path`) and `close_outcome`
(via `close_outcome_path`, if present). Deterministic tie-break if >1 schema matches (e.g. first by
`cohort_def_id` sort) — and since `correlation_value` alone resolves the instance, an ambiguous `cohort_def_id`
is non-fatal (log it). If `correlation_value` can't be extracted, treat as **no close match** (fall through to
triage), don't 500.

3b. **`/resolve` returns a discriminated result, back-compatible.** Check close-schemas **first**:
- close match → `200 {"kind": "cohort_close", "cohort_def_id", "correlation_value", "close_outcome": null|str}`.
- else run triage as today → the existing `ResolveResponse` (treat as `kind: "trigger"`; keep all current
  fields so existing consumers/tests are unaffected — add `kind` as optional/defaulted).
- else → `404` no-match as today.

Keep the existing resolve tests green (pack path unchanged); add tests for the close-match and
no-correlation-value-fallthrough paths.

### 4. Ingestor — branch on classification

4a. `RegistryClient.resolve` surfaces the `kind` (return the parsed body; don't collapse it). In
`_resolve_and_dispatch`, **before** building `TriggerDispatchedEvent`: if `kind == "cohort_close"`, publish a
`CohortCloseRequested` (with `correlation_value`, `close_outcome`, `cohort_def_id`, `Trace`) to the exchange
via the existing publisher, mark the ingestion record **terminal** with a new
`IngestionStatus.COHORT_CLOSE` (add it + a `mark_cohort_close` repo method for observability/dedup), log, and
return. Otherwise proceed exactly as today (pack dispatch). `RegistryNoMatch`/`RegistryUnavailable` behaviour
unchanged.

### 5. agent-runtime — close consumer + the drain to `closed`

5a. **Close consumer**: bind a durable queue to `ingestor.cohort_close_requested.v1`; handler parses the
payload into `CohortCloseRequested` and calls `CohortService.close(...)`. A bad message is logged + acked
(never poison-requeued), same as `DispatchConsumer`. Wire it in `main.py` alongside the dispatch consumer.

5b. **`CohortService.close(correlation_value, close_outcome)`** — resolve the cohort by `correlation_value`
alone.
- **No cohort** for that value → benign logged no-op, return (ADR: whole case ran externally, or a
  close/first-segment race).
- Otherwise drive the state machine with **atomic conditional updates** (the crux — get the race right):
  1. `begin_close`: `find_one_and_update({correlation_value, state: OPEN}, {$set: {state: CLOSING,
     close_outcome, updated_at}})`. If it matched nothing (already `closing`/`closed` — a duplicate close),
     it's idempotent → no-op, return.
  2. `finalize_if_drained`: `find_one_and_update({cohort_instance_id, state: CLOSING, active_member_count: 0},
     {$set: {state: CLOSED, closed_at, updated_at}})`.
  - If finalize matched → emit **`closed`** (no member was in flight). Else emit **`closing`** (members still
    running; the drain will finalize). **Exactly one** of the two events fires here.

5c. **Extend the drain** (`on_member_terminal` / `mark_member_terminal`): after a member is marked terminal,
if the cohort is now `state == CLOSING` **and** `active_member_count == 0`, run the **same**
`finalize_if_drained` conditional (atomic; only one caller can win it) and, on success, emit **`closed`**. This
is what turns "close arrived while members ran" into a real `closed` once the last member finishes. Member
terminal still emits **no** lifecycle event of its own (member instances publish their own terminal telemetry —
one source of truth).

5d. **Concurrency guarantee to prove:** a close racing the last member's terminal must yield **exactly one**
`closed` event and a consistent terminal row — because both finalize paths are the same atomic
`{state: CLOSING, active_member_count: 0}` conditional and only one `find_one_and_update` can match.

### 6. Late-join edges (now live)

Phase 1 already emits `late_join` when a segment joins a cohort whose `state == CLOSED`. Phase 2 makes `CLOSED`
reachable, so add the end-to-end test. A segment arriving while a cohort is `CLOSING` (not yet closed) joins
normally and increments `active_member_count` — the cohort correctly stays alive until it too finishes (the
"keep the cohort alive" rule). Do **not** treat a during-`closing` join as an anomaly.

## Tests (the headline is the drain races)

- **Registry:** cohort-definition CRUD; `close_schema` JSON-Schema validation; membership set/clear (unknown
  `cohort_def_id` → 4xx); `/resolve` returns `cohort_close` for a close envelope, `trigger` for a pack envelope
  (existing tests unchanged), `404` for neither; no-correlation-value close → fall through to triage.
- **Ingestor:** a close-classified envelope → `CohortCloseRequested` published + record `COHORT_CLOSE`
  terminal, **no** `trigger_dispatched`; a normal trigger still dispatches unchanged.
- **agent-runtime (drain state machine):**
  - close with **0 active members** (all already terminal) → `open → closed` directly, `closed` emitted once,
    no `closing`.
  - close with **≥1 active member** → `open → closing` (`closing` emitted); then each member terminal drains;
    the **last** one finalizes → `closed` emitted **once**.
  - **race:** close and the last member-terminal fired concurrently (`asyncio.gather`) → exactly one `closed`,
    final state `closed`, `active_member_count == 0`.
  - **duplicate close** on a `closing`/`closed` cohort → idempotent no-op (no extra events).
  - **no cohort** for the value → no-op, no crash.
  - a segment joining a **closed** cohort → `late_join`; a segment joining a **closing** cohort → normal
    `member_joined`, keeps it alive.

## Do not

- Do NOT build the GLEA `cohort_instances` read-model, cohort list/detail views, or the instance-view backlink
  — those are Phase 3. (Phase 2 only needs the events to be emitted; Phase 3 consumes them.)
- Do NOT give the cohort execution authority: close must **not** terminate/cancel any running segment.
- Do NOT require `cohort_def_id` on the close path — `correlation_value` is the sole handle (the external
  system stays unaware of Amendia ids). Uphold the global-uniqueness invariant.
- Do NOT emit a member-terminal lifecycle event; do NOT double-emit `closed`.
- Do NOT touch ADR-059/060/061/062 behaviour, HITL gating, or the type-compat guard.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- A cohort definition can be registered (with a validated close schema) and a pack version assigned/cleared of
  membership via the registry API.
- An inbound end-of-process message is recognised by `/resolve` (close-schema match), the ingestor publishes
  `CohortCloseRequested` (correlation_value only required), and agent-runtime drives `open → closing → closed`
  correctly — waiting for in-flight members, never terminating them.
- The close/last-member race yields exactly one `closed`; duplicate close is idempotent; no-cohort close is a
  no-op; closed-cohort late sibling → `late_join`.
- `pytest` green for `agent-runtime`, `process-registry`, `ingestor`, `amendia_contracts`, and any touched lib;
  existing `/resolve` and dispatch suites unaffected (regenerate the OpenAPI snapshot if the resolve response
  gained an optional `kind`).

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR063_phase2_cohort_definition_and_close_ingress_report.md`
(uncommitted): (1) outcome one-liner; (2) the `CohortCloseRequested` contract + routing key; (3) registry —
cohort-definition CRUD, membership assignment (and the in-place-vs-new-version call you made), the
`/resolve` fold + back-compat; (4) ingestor branch + new terminal status; (5) the close consumer + the
`close()` state machine and the **atomic finalize** design, with the race argument for exactly-one `closed`;
(6) tests added, especially the drain-race results; (7) verification commands + results; (8) anything deferred
to Phase 3 or left open. State clearly this is **Phase 2 of 3**. Keep it to a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Prefer the fix at the right layer over a shim (the
atomic conditional updates are the right layer for the close/drain race — do not reach for an app-level lock).
Stay inside the Amendia repo and the Phase-2 scope above.
