# ADR-064 P2 — cohort SLA runtime scheduling + evaluation: report

**This is P2 of 4** (runtime, agent-runtime, backend-only). P1 (definition model + validation, process-registry)
landed. P3 (GLEA read-model + endpoints) and P4 (webui) are separate prompts — none built here. No SSE /
notification-service / signal_mapper change (that's the P4 thin-signal step).

## 1. Outcome

A cohort whose definition carries an `expectation_graph` now **snapshots it at open**, **materialises durable
SLA timers**, **cancels-on-satisfy / voids** them from the existing fail-soft join/close path, **fires
overdue ones into `at_risk`/`breached`** (evaluate-and-flag, never resume), and **emits a `CohortSlaEvent`** —
exactly-once, crash-safe, owner-attributed. A cohort with **no** graph behaves exactly as ADR-063 (no snapshot,
no timers, no SLA state, no events). Zero execution authority: a breach only flags/records/attributes. All
agent-runtime suites green (**393 passed, 4 skipped**; +25 new).

## 2. The sibling SLA-timer subsystem (why sibling, not overload)

An SLA timer's fire-action **reads cohort/member state and flags** — it never resumes a parked LangGraph
interrupt. Sharing the ADR-027 instance `Timer` collection + poller would entangle the interrupt-resuming fire
path with an evaluate-only one. So P2 adds a **separate substrate** that mirrors ADR-027's shapes:

- **Collections** (`app/db/mongo.py`): `cohort_sla_expectations` (per-expectation SoR, unique
  `(cohort_instance_id, sla_id)`) and `cohort_sla_timers` (durable fire schedule, unique
  `(cohort_instance_id, sla_id, phase)`, scan index `(status, fire_at)`).
- **Models** (`app/models/cohort_sla.py`): `CohortSlaExpectation` and `CohortSlaTimer` (+ the enums
  `SlaExpectationKind/State`, `SlaMoment`, `SlaTimerPhase/Status`).
- **Repos** (`app/dal/cohort_sla_repo.py`): idempotent `register` (`$setOnInsert`), `due(now)`, guarded
  `mark(pending→fired)` CAS, `cancel_for_expectation`, and the guarded `transition(state ∈ expected → new)` CAS
  — the once-only gate the satisfy/void/fire paths race on. `fire_at` (and the expectation's temporal fields)
  are stored **native** (not the JSON string) so `$lte` is a real temporal comparison, exactly like `timer_repo`.
- **Poller** (`app/main.py` `_sla_poll`): a sibling of the timer poller, wakes every `AGENTRT_SLA_POLL_SECONDS`,
  calls `cohort_sla_service.fire_due()`. Durable rows → a restart re-fires anything overdue.
- **Row shape**: `{sla_timer_id, cohort_instance_id, sla_id, phase: at_risk|breach, fire_at, status}`. A
  **breach** row at `anchor + deadline` always; an **at_risk** row at `anchor + at_risk` when
  `0 < at_risk < deadline`.

## 3. Snapshot-at-open + the registry fetch

`RegistryClient.get_cohort_definition(id)` → `GET /cohort/definitions/{id}`. On the first member (cohort
`created`), `CohortSlaService.on_cohort_open` fetches the definition and, if it has an `expectation_graph`,
stamps it onto the `CohortInstance.expectation_graph_snapshot` (via `cohort_repo.set_sla_snapshot`, a guarded
`$eq:None` write so it's set once). **All** scheduling for the instance reads the **snapshot**, never the live
definition — an in-flight cohort keeps the expectations it opened under (the forward-only guarantee; a test
mutates the fake definition after open and confirms the snapshot + `registry.calls == 1`). No graph or a failed
fetch → no snapshot, no timers (fail-soft, ADR-063 behaviour).

## 4. Scheduling / cancel / void wiring + exactly-once + crash-safe

`CohortService` gained an optional `sla_service`; four **fail-soft** hooks (`_sla_hook` swallows any SLA error
with a warning) fire from the existing lifecycle path — so an SLA fault never breaks a segment or the lifecycle
emit, and unit tests without the substrate stay pure ADR-063:

| Lifecycle point | SLA hook | Action (from the snapshot) |
|---|---|---|
| open (first member) | `on_cohort_open` | snapshot; schedule every `__start__`-anchored edge SLA + `end_to_end_sla` (anchor = open instant) |
| `member_joined` (arrival of X) | `on_member_arrival` | **satisfy** arrival-satisfy SLAs targeting X; **void** XOR-sibling arrival expectations (other targets of the same `from_node`'s XOR out-set); schedule X's runtime `NodeSla` + any arrival-anchored edges from X |
| `on_member_terminal` (completion of X) | `on_member_completion` | **satisfy** completion-satisfy SLAs targeting X (incl. X's runtime SLA); schedule completion-anchored (next-hop arrival) edges from X |
| `close` (begin_close winner) | `on_cohort_close` | **satisfy** every close-satisfied SLA (`end_to_end` + edges into `__close__`); **void** all still-pending expectations |

- **Node id == the member's `pack_key`** (arrival) and the anchor is `now()` at the observed moment (deterministic
  under the injected clock).
- **Exactly-once**: firing = guarded `mark(pending→fired)` then a guarded `transition` CAS on the expectation
  (`pending→at_risk`, `{pending|at_risk}→breached`). Satisfy/void is the same CAS `{pending|at_risk}→
  satisfied|voided` + `cancel_for_expectation`. Only one terminal transition per expectation can win — the
  `finalize_if_drained` pattern. A satisfy/void that lands **after** a breach fired: the CAS misses (breached ∉
  `{pending,at_risk}`), the breach **stands**, and `arrived_late=True` is recorded (attribution keeps the truth).
- **Crash-safe**: rows are durable; the poller re-fires overdue rows on restart. Each breach stamps `due_at`
  (scheduled) **and** `detected_at` (`now()` at fire), so a late detection is honest (a test advances the clock
  5000s past the deadline before the first `fire_due` and asserts `detected_at > due_at`).

## 5. Persisted SLA state (what P3 reads)

One `cohort_sla_expectations` doc per expectation (the authoritative record P3's read-model + P4's UI fetch over
**REST**, never SSE): `{sla_id, cohort_instance_id, cohort_def_id, correlation_value, kind (edge|node|
end_to_end), ref, owner, clock, satisfy_node, satisfy_moment, split, from_node, state (pending|at_risk|
satisfied|voided|breached), anchor_at, due_at, at_risk_at, at_risk_marked_at?, satisfied_at?, voided_at?,
breached_at?, detected_at?, arrived_late, created_at, updated_at}`. `cohort_def_id`/`correlation_value` are
denormalised so the hot fire path + P3 read the row without a cohort join.

## 6. Business clock

`app/services/business_clock.py` — self-contained + unit-tested. `add_business_seconds(anchor, seconds,
calendar)` walks forward consuming seconds only inside working windows on working, non-holiday days.
`BusinessCalendar` = working weekdays + a daily UTC working-hours window + holiday dates. A single deployment
default is built from config (`AGENTRT_SLA_BUSINESS_DAYS` / `_START_HOUR` / `_END_HOUR` / `_HOLIDAYS`; default
Mon–Fri 09:00–17:00 UTC). `clock="business"` uses it for both `at_risk_at` and `due_at`; a mis-configured
calendar (no working days / zero window) degrades to wall (loud-in-hindsight). Multi-calendar / per-timezone is
a noted later refinement (isolated so the swap is contained).

## 7. `CohortSlaEvent` on the bus

`amendia_contracts.governance_events.CohortSlaEvent` (sibling of `CohortLifecycleEvent`, ADR-058-native), routing
key **`agent_runtime.cohort_sla.v1`** (`COHORT_SLA` added to `amendia_common.events`). Fields: `state (at_risk|
breached|satisfied|voided)`, `cohort_def_id`, `cohort_instance_id`, `correlation_value`, `sla_id`, `kind`, `ref`,
`owner`, `clock`, `due_at?`, `at_risk_at?`, `detected_at?`, `trace?`. Emitted **fail-soft** via
`publisher.emit_cohort_sla` on all four transitions (at_risk + breached required; satisfied + voided included —
cheap, useful for P3 rollups). No SSE / notification-service / GLEA / webui change here.

## 8. Verification (deterministic — injected clock, no sleeps)

`cd backend/services/agent-runtime && uv run --extra dev pytest` → **393 passed, 4 skipped**.

- `tests/test_cohort_sla_runtime.py` (**15**, real `CohortService` over mongomock + fake registry):
  - backward-compat: no graph → no snapshot/timers/expectations;
  - snapshot at open + START/e2e scheduling + `registry.calls == 1`; snapshot forward-only (definition mutated
    after open, not re-read);
  - **arrival satisfied before deadline** → satisfied, timer cancelled, no breach;
  - **arrival never arrives** → `at_risk` at `at_risk_at`, then `breached` at `due_at`, `owner="external"`;
  - **runtime/completion SLA** breach `owner="amendia"` (+ satisfied when the member finishes in time);
  - **XOR sibling arrival voids** the other branch (no breach);
  - **close voids** a still-pending arrival; **close satisfies** end-to-end; **end-to-end breaches** when close
    never comes (`owner="shared"`);
  - **satisfy after breach** → breach stands + `arrived_late`, exactly one breach event;
  - **fire racing satisfy** → exactly one terminal state, ≤1 breach event;
  - **crash-safe** overdue re-fire with `detected_at > due_at`;
  - **business vs wall**: a 1-working-hour deadline anchored Fri 16:30 lands Mon 09:30 and does **not** breach
    after 1 real wall-hour.
- `tests/test_business_clock.py` (**10**): within-day, roll-to-next-morning, clamp-to-open, weekend skip, holiday
  skip, full-day equivalence, business≠wall across a non-working window, zero/negative identity, misconfig→wall,
  config parsing.
- Existing cohort suites (`test_cohort_service`, `test_cohort_close_drain`, `test_cohort_repo`, …) pass unchanged.
- `CohortSlaEvent.routing_key()` == `agent_runtime.cohort_sla.v1` (smoke-checked).

## 9. Backward-compat

Confirmed: `sla_service` is optional on `CohortService` (unit tests / no substrate → the four hooks no-op); a
definition **without** `expectation_graph` opens/joins/drains/closes exactly as ADR-063 (no snapshot, no timers,
no SLA state, no events). No change to `join_on_spawn`/`on_member_terminal`/`close` observable lifecycle output.

## 10. Follow-ups

- **P3 (GLEA):** consume `agent_runtime.cohort_sla.v1` into a `cohort_events` read-model extension + an
  owner-attributed `sla_breaches` rollup; add a role-guarded REST endpoint returning a cohort's SLA state
  (the `cohort_sla_expectations` docs — pending/at-risk/breached with `owner`/`due_at`/`detected_at`). The
  agent-runtime SoR stays authoritative; GLEA is observability-grade.
- **P4 (webui + thin signal):** extend `notification-service/signal_mapper.py` `_ALLOWED_FIELDS` whitelist for a
  **thin SSE invalidation** signal carrying **ids/labels only** — `cohort_instance_id`, `cohort_def_id`, `sla_id`,
  `state`, `owner` (never `due_at`/`detected_at`/business content); the UI re-fetches authorized SLA data over the
  P3 REST endpoint. Tabular DAG+SLA editor on the definition detail; at-risk/breached chips + next-deadline
  countdown on the instance.
- **Determinism note:** START/e2e anchor on the open instant (`now()`), not the repo's real-time `opened_at`
  (equal within ms in production; keeps tests fully clock-driven).
- **Reviewer note:** live only after `docker compose build agent-runtime` (+ restart).
