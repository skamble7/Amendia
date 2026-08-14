# Claude Code prompt — ADR-064 P2: cohort SLA **runtime scheduling + evaluation** (agent-runtime, backend-only)

Second phase of **ADR-064 (Cohort SLAs)**. P1 landed the definition's `expectation_graph` + validation in
process-registry. P2 makes it live at runtime: **materialise durable SLA timers, evaluate them (at-risk -> breach),
cancel-on-satisfy, void conditionals, guarantee exactly-once, survive restarts**, and **emit a `CohortSlaEvent`
to the bus**. Per the agreed phase split, **P2 is bus emission + persisted state only** — no GLEA read-model
(P3), no SSE/notification-service/webui (P4). Read `backend/docs/adr/ADR-064-*.md` and the authoring guide first.

**Security boundary (holds for the whole feature):** the eventual browser signal is a *thin SSE invalidation
signal* (ids/labels only) and the UI re-fetches authorized SLA data over role-guarded REST — that wiring is
P3/P4 (extend `notification-service/signal_mapper.py` + a read endpoint). P2 does **not** add any SSE or
notification-service code. The service-to-service `CohortSlaEvent` on the bus may carry the fields GLEA needs
(GLEA consumes the bus, not the browser).

## Why / the model (from ADR-064)

Zero execution authority is preserved: a breach **flags, records, attributes** — it never aborts, forces, skips,
retries, or synthesises anything. An SLA = *after an anchor event, expect a satisfying event within a deadline
(+clock); else breach, owned by external/amendia/shared.* The **anchor map** (fixed by P1's report):

| Graph moment | Runtime event (agent-runtime) |
|---|---|
| `START` (cohort opens) | cohort `opened` (first member spawn) — `opened_at` |
| node **arrival** | that member `member_joined` (join_on_spawn) |
| node **completion** | that member reaches terminal (`on_member_terminal`) |
| `CLOSE` | close message received -> cohort `closed` |

## Read first (reuse the existing shapes + seams)

- `backend/services/agent-runtime/app/services/cohort_service.py` — the SoR service. The three hook points:
  **`join_on_spawn`** (emits `opened`/`member_joined`/`late_join` — this is **arrival** + cohort **open**),
  **`on_member_terminal`** (drain — this is **completion**), **`close`** (begin_close + finalize — this is
  **CLOSE**). Wire SLA scheduling/cancel/void into these, fail-soft (an SLA error must never break a segment or
  the observer — mirror the existing fail-soft emit).
- `backend/services/agent-runtime/app/models/cohort_instance.py` — `CohortInstance` (`cohort_instance_id`,
  `cohort_def_id`, `correlation_value`, `state`, `members[]` with `terminal`, `active_member_count`, `opened_at`,
  `closed_at`, `close_outcome`). SLA state + the snapshot graph get persisted here (or a sibling doc keyed by
  `cohort_instance_id`).
- `backend/services/agent-runtime/app/dal/cohort_repo.py` — `get_or_open` / `add_member` /
  `mark_member_terminal` / `begin_close` / `finalize_if_drained` (the atomic guarded transitions to mirror for
  exactly-once).
- `backend/services/agent-runtime/app/models/timer.py`, `dal/timer_repo.py`, `services/timer_service.py` — the
  **ADR-027 durable-timer pattern to mirror**: durable rows, `due(now)`, guarded `mark(pending->fired/cancelled)`
  CAS, and the **injectable `now` seam** (`fire_due(now)`) that makes timer tests deterministic with no sleep.
  **Do NOT overload this instance-Timer model or the engine's interrupt-resuming fire path** — SLA timers are
  cohort-scoped and their fire-action evaluates state (it never resumes a LangGraph interrupt). Build a
  **sibling** collection + poller (below), reusing these shapes.
- `backend/services/agent-runtime/app/clients/registry_client.py` — the registry HTTP client (`_get` + typed
  methods like `get_pack`). Add `get_cohort_definition(cohort_def_id)` -> `GET /cohort/definitions/{id}` to fetch
  the definition (incl. `expectation_graph`) at cohort open.
- `backend/services/agent-runtime/app/events/publisher.py` — `emit_cohort_lifecycle` (the aio-pika publish
  pattern: op enum, `to_doc()`, `routing_key()`, `event_id`). Add a sibling `emit_cohort_sla`. Mirror the
  `CohortLifecycleEvent` contract (in `amendia_contracts`) for a new **`CohortSlaEvent`**.
- `backend/services/agent-runtime/app/engine/engine.py` (~742/759/775) + `services/dispatch_service.py` (~168) —
  where `on_member_terminal` / `join_on_spawn` are already called. You hook the cohort_service methods, not
  these call sites.

## Deliverables

### 1. Snapshot the expectation graph at cohort open (forward-only, crash-safe)
When `join_on_spawn` **opens** a cohort (first member), fetch the definition via
`registry_client.get_cohort_definition(cohort_def_id)` and **snapshot its `expectation_graph` onto the
`CohortInstance`** (e.g. `sla_plan`/`expectation_graph_snapshot`). All SLA scheduling for this cohort reads the
**snapshot**, never the live definition — so an in-flight cohort keeps the expectations it opened under and later
definition edits don't touch it (this *is* the forward-only guarantee). If the definition has **no**
`expectation_graph` (or the fetch fails — fail-soft), the cohort runs exactly as ADR-063 today: no snapshot, no
timers, no SLA state. **Backward-compatible.**

### 2. A sibling durable SLA-timer subsystem (mirror ADR-027, don't overload it)
- New `cohort_sla_timers` Mongo collection + `CohortSlaTimerRepository` + a small poller
  (mirror `timer_repo`/`timer_service`: `register` (idempotent), `due(now)`, guarded `mark(pending->fired)`,
  `cancel(...)`, and a background loop like the existing timer poller / ingestor `_resolve_sweep`). Use the same
  **injectable `now` seam** so tests are deterministic.
- A timer row ~ `{sla_timer_id, cohort_instance_id, sla_id, phase: "at_risk"|"breach", fire_at, status}`.
  For each scheduled SLA schedule a **breach** row at `anchor + deadline_seconds` and (when `0 < at_risk_seconds
  < deadline_seconds`) an **at-risk** row at `anchor + at_risk_seconds`. `fire_at` respects the SLA's **clock**
  (below). Unique index `(cohort_instance_id, sla_id, phase)` -> idempotent re-register (crash replay).
- **Crash-safety:** rows are durable; on restart the poller re-fires anything overdue. A breach is stamped with
  both `due_at` (the scheduled deadline) and `detected_at` (`now()` at fire) so a breach detected late after
  downtime is honest — **late-but-never-missed**.

### 3. Scheduling — event-driven, from the snapshot
- **On open:** schedule every `START`-anchored edge SLA (anchor = `opened_at`) and the `end_to_end_sla`
  (anchor = `opened_at`, satisfied by `closed`).
- **On `member_joined` (arrival of node X):** (a) **satisfy** any pending *arrival-satisfy* SLA whose target is
  X; (b) schedule X's **runtime `NodeSla`** (arrival->completion, anchor = now); (c) **XOR-sibling voiding** — if
  X is reached by an XOR edge, **void** the still-pending arrival expectations of X's XOR siblings (the other
  targets of the same `from_node`'s XOR out-set, from the snapshot).
- **On `on_member_terminal` (completion of node X):** (a) **satisfy** X's runtime `NodeSla` and any
  *completion-satisfy* SLA targeting X; (b) **schedule** edge SLAs anchored on X's **completion** (the next-hop
  arrival timers, anchor = now).
- **On `close`/`closed`:** **satisfy** the `end_to_end_sla` (reaching `closed`), and **void all still-pending**
  SLA expectations (the close means the process ended — a not-yet-due expectation is excused; an *already-fired*
  breach stands). Cancel their timer rows.

### 4. Evaluation on fire (exactly-once, attributed)
When a row fires (poller, guarded `mark(pending->fired)` — only the winner proceeds):
- Re-read the per-expectation SLA state. If already `satisfied`/`voided`/`breached` -> **no-op** (the satisfy/void
  path won, or a duplicate). Otherwise:
  - **at_risk phase:** transition `pending -> at_risk` (guarded CAS on the expectation state) and `emit_cohort_sla`
    `state="at_risk"`.
  - **breach phase:** transition `{pending|at_risk} -> breached` (guarded CAS) and `emit_cohort_sla`
    `state="breached"` with `owner`, `due_at`, `detected_at`.
- **Cancel-on-satisfy / void** (steps 3b/3c/close): a guarded CAS `pending|at_risk -> satisfied|voided` on the
  expectation state, done **atomically with** the triggering state update in the existing handler, plus cancel
  the SLA's timer rows. A satisfy/void that lands **after** a breach fired leaves the breach standing but records
  `arrived_late`/resolution (never un-breaches) — attribution keeps the truth. Net: **exactly one terminal
  transition per expectation**, mirroring `finalize_if_drained`.

### 5. Persisted SLA state (for P3/P4 to read over REST)
Persist per-expectation state on the cohort instance (or a sibling doc): `{sla_id, kind (edge|node|end_to_end),
ref, owner, clock, state (pending|at_risk|satisfied|voided|breached), due_at, at_risk_at, satisfied_at?,
breached_at?, detected_at?}`. This is the authoritative record the P3 read-model/endpoint and the P4 UI will
fetch over REST (never via SSE).

### 6. Clocks — wall + business
- **wall:** `fire_at = anchor + timedelta(seconds=deadline)` (trivial).
- **business:** a self-contained `business_clock.py` helper — `add_business_seconds(anchor, seconds, calendar)` —
  against a **single deployment-configured default calendar** (working days + working-hours window + optional
  holiday list, from config). Keep it isolated and unit-tested; a richer multi-calendar/timezone story is a later
  refinement (note it). `clock="business"` uses this for both `at_risk_at` and `due_at`.

### 7. `CohortSlaEvent` on the bus
Add `emit_cohort_sla(publisher, *, state, cohort_def_id, cohort_instance_id, correlation_value, sla_id, kind,
ref, owner, due_at, detected_at, ...)` mirroring `emit_cohort_lifecycle` (fail-soft; routing key
`agent_runtime.cohort_sla.v1`). Emit on `at_risk` and `breached` (and optionally `satisfied`/`voided` if cheap —
useful for P3 rollups). **No** SSE / notification-service / GLEA / webui changes here.

## Do not

- Do not touch **process-registry** (P1 done), **glea-service** (P3), **notification-service**, or **webui** (P4).
  Do not add any SSE endpoint or `signal_mapper` change — that's the P4 thin-signal step.
- Do not overload the instance `Timer` model or the engine's interrupt-resuming fire path — sibling subsystem.
- Do not give the cohort any execution authority: never abort/gate/terminate a member, never re-emit a trigger.
  SLA logic is observation only, and **fail-soft** — an SLA failure must never break a segment or the lifecycle.
- Do not read the live definition after open — schedule from the **snapshot** (forward-only).
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance (deterministic — use the injectable `now` seam; no sleeps)

- **Backward-compat:** a cohort whose definition has no `expectation_graph` behaves exactly as ADR-063 (no
  snapshot, no timers, no SLA events).
- **Arrival satisfied before deadline** -> no breach (timer cancelled). **Arrival never arrives** -> `at_risk` at
  `at_risk_at`, then `breached` at `due_at`, `owner="external"`.
- **Runtime/completion SLA** breaches when a member overruns, `owner="amendia"`.
- **XOR sibling arrival voids** the other branch's pending arrival expectation (no breach).
- **Close voids** still-pending expectations; a breach that already fired **stands**; `end_to_end` satisfied on
  `closed` (or breaches if `closed` never comes in time).
- **Exactly-once:** a fire racing a satisfy yields exactly one terminal expectation state and at most one breach
  event. **Crash-safe:** an overdue timer re-fires after a restart with `detected_at > due_at`.
- **Business vs wall:** `business_clock` computes `at_risk_at`/`due_at` across a non-working window correctly;
  wall-clock is elapsed real time.
- agent-runtime `pytest` green incl. all the above. (No OpenAPI/webui change in P2.)
- **Reviewer note:** live only after `docker compose build agent-runtime` (+ restart).

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR064_phase2_cohort_sla_runtime_report.md` (uncommitted):
(1) outcome one-liner; (2) the sibling SLA-timer subsystem (collection, repo, poller, row shape) + why sibling
not overload; (3) snapshot-at-open + the registry fetch; (4) the scheduling/cancel/void wiring into
join/terminal/close and the exactly-once CAS + crash-safe re-fire; (5) the persisted SLA-state shape (what P3
reads); (6) business-clock approach + its config; (7) `CohortSlaEvent` shape + routing key; (8) verification —
exact `pytest` commands + results for every acceptance bullet; (9) backward-compat confirmation; (10) follow-ups
for P3 (GLEA consumer + read endpoint) and the P4 `signal_mapper` whitelist (which id fields the thin SSE signal
should carry). One screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. agent-runtime-only. Reuse the ADR-027 timer patterns +
the `finalize_if_drained` CAS style; keep SLA logic **fail-soft, observation-only, forward-only (snapshot)**, and
deterministic via the injectable clock. Smallest change that makes the P1 model live and testable end-to-end at
the runtime, leaving surfacing to P3/P4.
