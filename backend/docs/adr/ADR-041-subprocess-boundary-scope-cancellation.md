# ADR-041 — Interrupting boundaries on a sub-process (scope-level cancellation)

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-040 (single-node cooperative cancellation —
this **extends the primitive from one node to a whole scope**), ADR-032 (sub-process inline-flatten), ADR-029/030
(timer/error boundary router). **Backlog:** Wave-3 item **#5** — scope-level interruption; the event sub-process
(F) and side-effectful/HITL scopes (G) remain deferred.

## Context — the key fact

A `subProcess` is **inline-flattened** into the parent graph (ADR-032): the box disappears at compile and its
inner nodes wire directly into the parent. So a boundary on the box has **no single runtime node to attach
to** — it must be **projected onto the inner nodes** of the scope. Scope membership is already tracked
(`model.element_scope`, `SubProcess.member_ids`). Two boundary kinds, two mechanisms. Both were refused
(`bpmn_subprocess_boundary_unsupported`).

## Decision

### A · Error boundary on a subProcess — a routing fallback (low risk)

Parser: an error boundary whose `attachedToRef` is a subProcess is recorded in `error_boundaries[subprocess_id]`
(the model already keys boundaries by host id). Compiler: an inner node's boundary router, after the node's
**own** error boundaries, layers the **enclosing scope chain's** error boundaries (walk `element_scope` outward,
inner→outer), so an unmatched modeled error checks each enclosing scope's handler (by code, then catch-all)
before `FAILURE_SINK`. **Inner-most matching handler wins.** No running work is interrupted — it fires when an
inner node *raises* a `CapabilityBusinessError`.

### B · Timer boundary on a subProcess — scope-level cancellation (the ADR-040 extension)

Parser: a timer boundary on a subProcess is recorded in `boundary_timers[subprocess_id]`. Compiler:

- **Scope-entry stamp.** The flow into the subProcess resolves to a lightweight **scope-entry node** that stamps
  `state.scope_deadlines[scope_id] = clock() + duration` (a new merge-dict `state.py` channel, injected clock)
  then edges to the scope's start-successor.
- **Per-inner-node enforcement (reuse ADR-040).** Every inner node runs under `min(its own boundary timer, the
  remaining scope budget)` — the ADR-040 `_run_autonomous_with_deadline` now takes a list of
  `(absolute_deadline, breach_key)` and enforces the earliest. On scope-deadline breach the inner node commits
  nothing and writes `boundary[scope_id] = {"kind":"timer"}`.
- **Between-node diversion.** Every inner node's router also checks the scope timer mark — if
  `boundary[scope_id].kind == "timer"`, it routes to the **scope timer-boundary target** (skipping the rest of
  the scope). So a breach detected by any inner node diverts the whole scope; a linear scope's remaining inner
  nodes never run.
- **All-or-nothing / re-entrancy.** Identical to ADR-040 — no partial artifact on the interrupted node; the
  checkpoint carries only the scope boundary mark; re-run-from-top is idempotent (the scope deadline re-arms
  fresh at the scope-entry node, same in-process-vs-durable honesty as ADR-040).

### C · Safety guards (consistent with ADR-040)

An interrupting **timer** boundary on a subProcess may contain **only autonomous `read_only` capability tasks**.
A **side-effectful** task in the scope is refused (`bpmn_subprocess_boundary_side_effect_unsupported` — cancelling
committed side effects is compensation, Item G); a **HITL gate** in the scope is refused
(`bpmn_subprocess_timer_scope_hitl_unsupported` — a parked-gate SLA is the idle-gate case, ADR-029). Both are
cross-contract registry checks (need the binding's `side_effect`/`hitl`), with a fail-closed compiler guard. The
**error** boundary has no such restriction (it doesn't cancel running work). `bpmn_subprocess_boundary_unsupported`
is retired for timer + error; other boundary kinds (message/signal/escalation) and callActivity boundaries (ADR-039)
stay refused.

## Consequences

- A `subProcess` with a timer boundary self-enforces a scope-wide SLA (each inner node under the remaining scope
  budget; a breach by any inner node diverts the whole scope to the handler, committing nothing, re-entrant),
  and a `subProcess` with an error boundary routes an uncaught inner modeled error to the scope handler (nested
  inner→outer) via the existing router. ADR-040 single-node SLA, the idle-gate SLA, embedded sub-process
  (ADR-032), and all non-boundary flows are byte-unchanged.

## Deferred / non-goals (recorded in the backlog)

- **Event sub-process** → **Item F** (the remaining Wave-3 construct).
- **Side-effectful** work inside an interrupting-timer scope and **HITL** inside one → **Item G** (compensation).
- **Non-interrupting** boundaries; **message/signal/escalation** boundaries on a subProcess.
- **External / asynchronous preemption** — still out (ADR-040's argument holds at scope granularity: interruption
  is between inner nodes + node-self-enforced, never mid-node by external preemption).
