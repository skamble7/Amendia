# ADR-043 — Compensation (explicit compensate-throw + reverse-order undo)

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-040/041 (cooperative cancellation — whose
"→ Item G" guards deferred exactly *this*: reversing a **committed** side effect), ADR-032 (inline-flatten —
the off-flow handler is inlined like an ESP body), ADR-030 (a modeled failure is what precedes a compensate
throw on the failure branch). **Backlog:** item **#4** — the last and heaviest deferred item. A **bounded
core cut**: explicit throw + scope-wide reverse-order undo; transaction/cancel, targeted, and multi-instance
compensation stay deferred.

## Context — the key fact

Compensation only *means* something if a side-effectful capability exposes a real **undo** — reversing a
release, a debit, a booking. BPMN expresses this with a **triad**: a compensation **handler** activity
(`isForCompensation="true"`, off the sequence flow, bound to the undo capability); a compensation
**boundary event** (`compensateEventDefinition`, `attachedToRef` = the compensable primary) that pairs the
primary to its handler via an `<association>`; and a compensate **throw** event that, when reached, undoes the
completed compensable activities of its scope in **reverse (LIFO) order**. The hard property is
**re-entrancy**: an undo is itself a side-effectful, HITL-gated step, so the driver must never undo the same
activity twice across an HITL-resume replay or a crash recovery.

## Decision

### A · Parse the triad (`amendia_bpmn`)

`isForCompensation` activities are captured as **off-flow handlers** (kept bound, excluded from reachability
+ the single-outgoing arity check, like an ESP body). A compensate boundary + its `<association>` build
`CompensationHandler{handler_id, primary_id, boundary_id}` and the inverse `compensations[primary]=handler`.
A compensate throw (`intermediateThrowEvent`/`endEvent` + `compensateEventDefinition`) becomes a
`CompensateThrow{id, scope, is_end, activity_ref}`.

### B · The compensation log (state)

`state.compensation_log` is an **append-only** channel (`operator.add`). A compensable primary, on its
side-effect **commit**, appends `{activity_id, handler_id, scope, snapshot, at}` (the task runner does this
in `_commit`, so every commit path is covered). Completion order = list order, so **LIFO = reversed**. A
companion `compensations_done` merge-dict (activity_id → true) records what has been undone — the append-only
log can't be mutated in place, so "compensated" lives in this second channel.

### C · The compensate-throw driver (the core mechanism)

Each throw compiles to a **self-looping driver node** (`app.engine.compensation`). Per superstep it picks the
**most-recently-completed not-yet-compensated** activity in its scope (LIFO, de-duped by activity id) and runs
that activity's bound handler through the **ordinary task-runner path** — so the undo runs behind its normal
**HITL gate** (compensation may pause for human approval, per handler — the correct payments behavior). It
marks the activity in `compensations_done` as the undo commits; the conditional edge loops back while any
pending remain, then proceeds to the throw's continuation (its outgoing flow, or `END` with `outcome` = the
throw id for a terminal end-event throw). Handlers are **inlined** (invoked by the driver), never graph nodes.

**Re-entrancy / no double-undo (the crux).** One activity per superstep means the driver node has **at most one
`interrupt`** (the handler's gate) — so LangGraph's existing single-interrupt-per-node guarantee (already relied
on for every `approve_actions` task) makes the undo `execute` run exactly once on the final resume pass, even
though the node re-runs from the top on each resume (propose is side-effect-free). Across supersteps, the
persisted `compensations_done` flag skips an already-undone activity. So a crash-replay or an HITL-resume
replay **never compensates the same activity twice** — proved by an integration test (each undo capability runs
exactly once through the gated, replay-heavy `drive()` flow) and a unit test of the pending selector.

### D · Validation + compilability

Compensation joins `common_executable`. The shared gate refuses the deferred variants:
`bpmn_compensation_transaction_unsupported` (a `cancelEventDefinition` — transaction auto-compensation),
`bpmn_compensation_targeted_unsupported` (`activityRef` on the throw — this cut is scope-wide),
`bpmn_compensation_multi_instance_unsupported` (a compensable primary/handler that is an MI host); a throw with
no compensable activity in scope is a no-op **warning** (`bpmn_compensate_throw_no_handlers`). The
cross-contract checks (registry): a compensable primary must be **side-effectful**
(`bpmn_compensation_handler_not_side_effect` — undoing a read-only step is meaningless) and its handler must be
a bound capability (`bpmn_compensation_handler_unbound`). A compensate boundary with no association to a bound
handler is a parser well-formedness error (`bpmn_compensation_boundary_unwired`).

## Consequences

- A completed side-effectful `serviceTask` with a compensation boundary logs a compensation entry on commit; a
  compensate throw undoes the scope's completed compensable activities in **reverse order** by running each
  one's bound undo capability **through its HITL gate**, marking each done so re-execution never double-undoes.
  The `payment-compensation` seed runs both paths (happy: no compensation; failure: release+debit reversed
  LIFO). All prior paths (A–F, the Wave-3 foundation) are **byte-unchanged** — the compensation-log append is
  gated on a per-node `compensate_handler_id` that is `None` everywhere else. No contract-model / OpenAPI
  change (the compensation model is internal to `amendia_bpmn`; the two new state channels are additive).

## Deferred / non-goals (recorded in the backlog)

- **Transaction sub-process** + **cancel end event** (automatic compensation on transaction cancel) — the throw
  here is **explicit**.
- **Targeted** compensation (`activityRef` → one activity) — this cut is scope-wide.
- Compensation of **multi-instance / looped** activities; **nested** compensation; **error-boundary-triggered**
  automatic compensation; a **capability-native `compensate` operation** (inline undo on the descriptor, vs a
  separate handler activity — a noted alternative).
- A **compensation-authorization batch gate** (approve all undos at once) — this cut gates per handler.
- **External / asynchronous** anything (the ADR-040 argument holds).
