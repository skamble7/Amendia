# ADR-063 Phase 2 — cohort definition registration + close ingress + drain: report

**This is Phase 2 of 3.** Phase 1 (runtime foundation) is landed. Phase 3 (GLEA read-models + webui) is a
separate prompt and is **not** built here — Phase 2 only emits the events Phase 3 will consume.

## 1. Outcome

A cohort definition (with a validated close schema) can be registered and a pack version assigned/cleared of
membership via the registry API; an external end-of-process message is recognised by `/resolve` (close-schema
match), the ingestor publishes `CohortCloseRequested` (correlation_value the sole handle), and agent-runtime
drives `open → closing → closed` — waiting for in-flight members, **never terminating them**. The close/last-
member race yields **exactly one** `closed`. Purely observational, zero execution authority. All suites green.

## 2. Contract — `CohortCloseRequested`

`libs/amendia_contracts/.../cohort_events.py`: `EventBase`, `_service = Service.INGESTOR`, `_event_name =
COHORT_CLOSE_REQUESTED` (new const in `amendia_common/events.py`). Routing key **`ingestor.cohort_close_requested.v1`**.
Structural/domain-neutral fields: `correlation_value` (the SOLE resolving handle — the external system never
learns Amendia ids), `close_outcome: Optional[str]`, `cohort_def_id: Optional[str]` (logging/validation only,
never required to resolve), `Trace`.

## 3. Registry — definition, membership, and the `/resolve` fold

- **Cohort definition** (`models/cohort.py`, `dal/cohort_def_repo.py`, `cohort_definitions` collection, **unique
  index on `cohort_def_id`**): `cohort_def_id`, `display_name`/`description`, `close_schema` (JSON Schema),
  `close_correlation_path`, `close_outcome_path`. Router `routers/cohort.py`: `POST/GET/GET{id}/DELETE
  /cohort/definitions`; register **validates `close_schema` is a well-formed JSON Schema**
  (`Draft202012Validator.check_schema` → 422) and requires a non-empty `close_correlation_path`. Authoring is
  `role.process.owner`; reads take a principal (same guards as packs).
- **Membership assignment** (`PUT`/`DELETE /packs/{pack_key}/{version}/cohort-membership`): validates the
  `cohort_def_id` exists (else 422) and `correlation_key` is non-empty, then stamps the stored manifest's
  `cohort_membership` **in place** and invalidates the resolver cache.
  - **In-place vs new version (the call I made):** membership is stamped **in place, no new pack version**.
    Rationale: `cohort_membership` is additive *observational* metadata — it does not change triage, compilation,
    binding, HITL, or execution (it only affects join-on-spawn's observation). Forcing a version bump for an
    observability tag would be heavyweight and churn the runtime bundle. **Flag for the team:** if membership
    must be version-immutable/audited-as-a-release, move it behind activation instead — this is a deliberate,
    reversible call, surfaced rather than decided silently.
- **`/resolve` fold (back-compat)** (`services/cohort_classifier.py` + `routers/resolve.py`): a `CohortClassifier`
  validates the envelope against every registered `close_schema` and, on a match, extracts `correlation_value`
  (via `close_correlation_path`) and `close_outcome`. `/resolve` now checks **close first**:
  - close match → `200 {"kind":"cohort_close", cohort_def_id, correlation_value, close_outcome}`.
  - else triage as today → `ResolveResponse` now carrying **`kind:"trigger"`** (added as a defaulted field, so
    every existing consumer/test that reads `pack_key/pack_version/rule_id` is unaffected).
  - else → `404`, unchanged.
  - Deterministic tie-break if >1 close schema matches (first by `cohort_def_id`; logged) — non-fatal because
    `correlation_value` alone resolves the instance. A schema match that yields **no** `correlation_value` is
    treated as **no close** (falls through to triage), never a 500.

## 4. Ingestor — branch on classification

`RegistryClient.resolve` already returns the parsed body (kind surfaced). In `_resolve_and_dispatch`, **before**
building `TriggerDispatchedEvent`: if `kind == "cohort_close"` → `_publish_cohort_close` marks the record
terminal `IngestionStatus.COHORT_CLOSE` (new status + `mark_cohort_close` repo method + a `cohort_close` record
field, for observability/dedup) **and only then** publishes `CohortCloseRequested` (so a redelivery that loses
the transition guard doesn't double-publish) — **no** `trigger_dispatched`. Otherwise dispatch proceeds exactly
as before; `RegistryNoMatch`/`RegistryUnavailable` behaviour unchanged.

## 5. agent-runtime — close consumer + the close state machine (the atomic finalize)

- **Close consumer**: `DispatchConsumer`'s binding key is now a constructor arg (`binding_key`, default the
  trigger key); `main.py` wires a second instance bound to **`ingestor.cohort_close_requested.v1`**
  (`RABBITMQ_COHORT_CLOSE_QUEUE`) whose handler parses `CohortCloseRequested` and calls `CohortService.close`.
  Same reconnect/ack discipline — a bad message is logged + acked, never poison-requeued.
- **`CohortService.close(correlation_value, close_outcome)`** — resolve by `correlation_value` alone:
  - No cohort → benign logged no-op.
  - `begin_close`: atomic `find_one_and_update({correlation_value, state: OPEN} → CLOSING)`. Matched nothing
    (already closing/closed) → **idempotent** no-op.
  - `finalize_if_drained`: atomic `find_one_and_update({cohort_instance_id, state: CLOSING, active_member_count:
    0} → CLOSED)`. Matched → emit **`closed`** (no member was in flight, `open → closed` directly). Else → emit
    **`closing`**. **Exactly one** of the two fires.
- **Drain extended** (`on_member_terminal` / repo `mark_member_terminal` returns the updated cohort): after a
  member is marked terminal, if the cohort is now `CLOSING` **and** `active_member_count == 0`, run the **same**
  `finalize_if_drained`; on success emit **`closed`**. Member terminal still emits **no** lifecycle event.
- **Exactly-one-`closed` race argument (5d):** both the close path and the last member's drain call the identical
  atomic conditional `{state: CLOSING, active_member_count: 0} → CLOSED`. In any interleaving, only **one**
  `find_one_and_update` can match that predicate (the first flips `state` to `CLOSED`; the second sees `CLOSED ≠
  CLOSING` and matches nothing), so exactly one caller finalizes → exactly one `closed`. No app-level lock — the
  atomic conditional is the right layer (per the working agreement).

## 6. Late-join edges (now live)

Phase 1's `join_on_spawn` treats `state == CLOSED` as the anomaly → `late_join`; a `CLOSING` cohort is **not**
an anomaly (`is_closed` is false), so a segment arriving mid-`closing` joins normally (`member_joined`) and
increments `active_member_count`, correctly keeping the cohort alive until it too finishes. No code change
needed — Phase 2 only makes `CLOSED` reachable; tests now exercise both edges end-to-end.

## 7. Tests added (35 total across the change; the headline is the drain races)

- **Registry** (`test_cohort_phase2.py`, 9): definition CRUD (+duplicate 409); malformed `close_schema` → 422;
  membership set/clear; unknown definition → 422, unknown pack → 404; `/resolve` → `cohort_close` for a close
  envelope, `trigger` (with `kind`) for a pack envelope, `404` for neither; close-schema match **without** a
  correlation value → falls through to triage.
- **Ingestor** (`test_cohort_close.py`, 3): close-classified → `CohortCloseRequested` published + record
  `cohort_close` terminal, **no** `trigger_dispatched`; normal trigger unchanged; duplicate close delivery
  publishes once.
- **agent-runtime** (`test_cohort_close_drain.py`, 6): close with **0 active** → `open → closed` directly
  (`closed`×1, no `closing`); close with **≥1 active** → `closing` then drains to `closed`×1; **race** (close +
  last member-terminal via `asyncio.gather`) → **exactly one `closed`**, final `closed`, `active_member_count ==
  0`; duplicate close → idempotent; no-cohort close → no-op; join to `closed` → `late_join`, join to `closing` →
  normal `member_joined` (kept alive). (Plus the Phase-1 cohort suites still green.)

## 8. Verification

- `process-registry`: **375 passed** (+9; includes the regenerated OpenAPI snapshot — `/resolve` gained
  `kind`, new `/cohort/definitions` + `/cohort-membership` routes; `python scripts/dump_openapi.py`).
- `agent-runtime`: **364 passed, 4 skipped** (+6).
- `ingestor`: **23 passed** (+3).
- Lib-consumer regression check: `glea-service` **49**, `stub_trigger_generator` **39**, `notification-service`
  **18** — all passed (contract/const additions are purely additive).
- `amendia_contracts` has no standalone suite; its additions are exercised via the service suites above.

## 9. Deferred to Phase 3 / left open

- **Phase 3:** GLEA `cohort_instances` read-model + instance-read-model cohort columns; cohort list/detail read
  APIs; webui cohort views + instance-view backlink. Phase 2 emits `opened`/`member_joined`/`late_join`/
  `closing`/`closed` fail-soft; Phase 3 consumes them.
- **Frontend follow-up (not Phase 2):** `webui/openapi/registry.json` was re-dumped, so `webui`'s
  `gen:api:check` will want a `cd webui && npm run gen:api` + commit.
- **Membership immutability** — flagged in §3 as an in-place call; revisit if the team wants it release-gated.
- **Invariant reminder:** V1 rests on `correlation_value` being globally unique (ADR-063 Assumptions); the
  registry classifier + the runtime close path both rely on it (correlation_value alone resolves the cohort).
- **No-TTL:** a cohort whose orchestrator never emits the close message stays `open` indefinitely (accepted for
  V1 — no auto-close).
