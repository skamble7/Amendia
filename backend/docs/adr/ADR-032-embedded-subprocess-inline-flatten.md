# ADR-032 — Embedded sub-process: inline-flatten (Common-Executable ladder rung 4)

**Status:** Accepted · **Date:** 2026-07-17 · **Builds on:** ADR-027 (BPMN conformance / execution
profiles), ADR-029 (timers), ADR-030 (error boundary), ADR-031 (messages), Phase 2.5 (per-pack
profile pin + load guard).

## Context

**Rung 4 of the Common-Executable ladder** — and the first that is **structural, not a new
substrate**. An embedded `subProcess` is a nested scope with its own start/end and internal flow. The
pragmatic execution model is to **inline (flatten) the sub-process into the parent graph**, so
everything already built — HITL, timers, messages, error boundaries, artifact validation, SoD — works
*inside* a sub-process with **zero new runtime machinery**. The care is entirely in the **parser**
(scoped start/end + recursion) and the **compiler** (inline wiring).

## Decision

**Flatten embedded sub-processes into one `StateGraph`.**

- **Parser is scope-aware (2.6.a).** The parser recurses into each `subProcess`, tracking containment
  (`element_scope`), and flattens nested flow nodes/gateways/events into the shared executable
  collections (so a nested `serviceTask` is just another task). The `subProcess` container is
  **structural** — retained in a `subprocesses` map (`{start_id, end_ids, member_ids, parent_scope,
  incoming_flow, outgoing_flow}`), never bound or executed as a node; its start/end become edges.
  Arbitrary nesting via recursion (element ids are globally unique, so flattening never collides).
- **Scoped start/end (the key correctness fix).** The **top-level** process still requires exactly one
  start; **each embedded sub-process requires its own single start + ≥1 end** (`scope_starts` /
  `scope_ends`). A nested start does **not** count against the top-level single-start rule.
  Reachability / path-to-end run on the **flattened** graph (virtual edges: box → its start; each
  internal end → the box's parent-level outgoing) so a node buried in a sub-process is checked end to
  end.
- **Compiler inlines (2.6.c).** `resolve_node` maps a flow targeting a sub-process box to its start's
  successor, and a flow targeting an internal (nested) end to the box's parent-level outgoing target —
  both recursing. So the parent-incoming flow lands on the sub-process's first real node, every
  internal end converges on the sub-process's parent outgoing, and the start/end become edges. Nested
  tasks/gateways/events/HITL/timers/messages/boundaries compile as ordinary nodes on the flat graph —
  **identical** to top level, which is the whole point.
- **Bijection recurses (2.6.d).** `bindable_elements()` is already computed from the (now flattened)
  executable collections, so **every nested serviceTask/userTask/messageCatch/receiveTask joins the
  binding bijection** — no orphans; the `subProcess` container needs no binding. Onboarding's inventory
  captures sub-process containment (`subprocesses: {id, name, member_ids}`) for grouping + the coverage
  overlay; the webui renders each sub-process as an executable group.
- **Profile (2.6.e).** `subprocess` is appended to `EXECUTION_PROFILES` as the next **cumulative** rung
  (above `messages`). `required_profile(model)` returns it when the executable core has an embedded
  sub-process; Phase-2.5's derived pin + load-time `>=` guard carry over. `compilability_findings`
  accepts embedded sub-processes under `subprocess`, refuses under lower, and **always** refuses the
  deferred constructs. Default stays `common_subset`.

## Consequences

- Embedded sub-processes (arbitrarily nested) compile by inlining and run end to end, with scoped
  start/end validation. Every capability built so far works unchanged inside a sub-process (proven: a
  nested serviceTask runs and commits its artifact; a nested HITL gate materializes + resumes + the
  flow completes; a nested timer catch / message catch / error boundary flatten into the executable
  collections and wire identically; a 2-level nested sub-process compiles + runs).
- No new runtime substrate, no engine changes — the win is entirely parser + compiler.

## Deferred / non-goals (cleanly refused)

- **`callActivity`** (a reusable process referenced by `calledElement`) — raises cross-pack composition
  questions (which pack/version, IO mapping, pinning) that are a separate design. Refused with
  `bpmn_call_activity_unsupported`.
- **Boundary events on a `subProcess` box** (interrupting timer/error on the scope, error propagation
  out of the scope) — refused with `bpmn_subprocess_boundary_unsupported` (deferred, like
  timer-boundary-on-serviceTask).
- **Event sub-process, transaction/compensation sub-process, ad-hoc sub-process, multi-instance
  markers** — deferred/annotated.
- No new runtime substrate; no concurrent human gates; no default-profile change. Cumulative-linear-rank
  assumption per ADR-029/030/031 still holds — the profile levels will likely collapse to a single
  `common_executable` alias once the construct set is complete.
