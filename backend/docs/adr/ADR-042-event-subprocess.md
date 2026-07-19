# ADR-042 — Event sub-process (scope-wide interrupting error/timer handler)

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-041 (subProcess boundary scope-cancellation —
this **generalizes the enclosing scope from a subProcess to the whole process** and adds the inlined-body
handler), ADR-040 (single-node cooperative cancellation), ADR-032 (sub-process inline-flatten), ADR-029/030
(timer/error boundary router). **Backlog:** Wave-3 item **#5** — the **event sub-process** (Item F), the last
Wave-3 construct. Non-interrupting / message-triggered / nested ESPs and compensation (Item G) remain deferred.

## Context — the key fact

An **event sub-process** (`subProcess triggeredByEvent="true"`) is not a box on the sequence flow — it is a
**scope-wide event handler**. Its *start event's trigger* makes it fire from **anywhere in its enclosing
scope**, and that enclosing scope may be the **whole process** — something a boundary on a subProcess (ADR-041)
structurally cannot express (a boundary must attach to an activity). Otherwise it is almost exactly the
ADR-041 machinery: on an interrupting trigger, **cancel the enclosing scope** and **run the handler**.

Two differences from a subProcess boundary drove the design:
1. **The enclosing "scope" may be the whole process.** ADR-041 keyed scope boundaries by a subProcess id and
   walked `element_scope` outward, stopping at the process. Here the process itself is a scope.
2. **The handler is the ESP body, inlined** — not a separate boundary flow to an escalation node. The body's
   start-successor is the handler entry; the body's ends are terminal (they end the instance).

## Decision

### A · Parse — detect + register the handler onto its enclosing scope

The parser records a `triggeredByEvent="true"` subProcess as an `EventSubProcess` (its own collection, **not**
`subprocesses` — it sits on no sequence flow, so it skips the box structural/arity checks). It reads the start
event's trigger:

- an **interrupting `error`** start → registered as a scope-wide **error boundary** on `enclosing_scope`
  (`error_boundaries[enclosing_scope]`, `error_code` = the matched code or `None` for catch-all);
- an **interrupting `timer`** start → registered as a scope-wide **timer boundary** on `enclosing_scope`
  (`boundary_timers[enclosing_scope]`), the scope-wide SLA;
- a **message/signal/escalation** start, or a **non-interrupting** ESP → recorded `unsupported`.

In every case the handler **target is the body's start-successor** (the inlined body's first node). By reusing
`boundary_timers` / `error_boundaries`, the ADR-041 router runs **unchanged** — the only generalization is that
a scope key may now be `process_id`.

### B · Compile — generalize the scope machinery + inline the body

- **Scope sets** (`subproc_timers` / `subproc_errors` / `_enclosing_scopes`) now recognize a scope that is a
  subProcess **or** an ESP's `enclosing_scope` (including `process_id`). `_enclosing_scopes` yields the whole
  process last when a process-level ESP guards it.
- **Process-level timer scope-entry.** A process-level timer ESP has no box to stamp the SLA deadline at — so
  the `START` edge routes through the scope-entry (deadline-stamp) node first, then to the normal start
  successor. A subProcess-scoped timer ESP is byte-identical to ADR-041 (stamped at the subProcess entry).
- **The ESP body is the handler.** Its start-successor is the handler entry (the router already routes there);
  its ends are added as **terminal END nodes**; its inner nodes are **excluded from every scope handler** (the
  handler is not subject to the scope it handles — nested ESP is deferred).
- **Inner-most matching handler wins** — the ADR-041 layering already gives: a node's **own** boundary, then
  each enclosing scope inner→outer (subProcess ESP, then process ESP), then `FAILURE_SINK`.

### C · Safety guards (consistent with ADR-041)

An interrupting **timer** ESP scope — subProcess **or the whole process** — may contain only autonomous
`read_only` capability tasks. A **side-effectful** task in the scope is refused
(`bpmn_subprocess_boundary_side_effect_unsupported` — compensation, Item G); a **HITL gate** is refused
(`bpmn_subprocess_timer_scope_hitl_unsupported` — the parked-gate SLA is ADR-029). The registry's
cross-contract check + the fail-closed compiler guard both now treat `process_id` as a scope and exclude the
ESP body. New refusals: `bpmn_event_subprocess_unsupported` (message/signal/escalation or non-interrupting
start) and `bpmn_event_subprocess_ambiguous` (two same-trigger ESPs on one scope — a duplicate timer handler,
or two error handlers catching the same code). The **error** ESP has no read_only restriction (it doesn't
cancel running work).

## Consequences

- A process can carry a **scope-wide error handler** (catch a modeled business error raised anywhere → run a
  handler) and a **scope-wide SLA** (a breach anywhere cancels the process and runs a handler), at process
  level or nested in a subProcess, with inner-most-wins precedence — reusing the ADR-041 router and the ADR-040
  cooperative-cancellation primitive. The `event-handler` seed pack demonstrates both.
- ADR-040 single-node SLA, ADR-041 subProcess boundaries, the idle-gate SLA, embedded sub-process (ADR-032),
  and all non-ESP flows are **byte-unchanged** (a subProcess-scoped ESP registers exactly as an ADR-041 boundary
  would). No contract-model / OpenAPI change (the `EventSubProcess` model is internal to `amendia_bpmn`).

## Deferred / non-goals (recorded in the backlog)

- **Non-interrupting** event sub-processes (a concurrent handler that does not cancel the scope).
- **Message/signal/escalation-triggered** ESPs — need a scope-duration subscription (like the deferred
  message/signal boundaries).
- **Nested** ESPs, an **ESP with its own boundary**, and ESP **self-retrigger**.
- **Side-effectful** work inside an interrupting-timer scope and **HITL** inside one → **Item G** (compensation).
- **External / asynchronous preemption** — still out (ADR-040's argument holds at scope granularity: interruption
  is between nodes + node-self-enforced, never mid-node by external preemption).
