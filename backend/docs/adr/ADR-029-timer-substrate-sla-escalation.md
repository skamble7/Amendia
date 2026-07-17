# ADR-029 — Timer substrate: SLA deadlines & escalation (Common-Executable ladder rung 1)

**Status:** Accepted · **Date:** 2026-07-17 · **Builds on:** ADR-027 (BPMN conformance / execution
profiles), ADR-028 (parallel spike + the ladder shape), Phase 2.5 (per-pack profile pinning + load
guard).

## Context

ADR-027 §2.2 sets out a Common-Executable *ladder* — promote one BPMN construct per rung from
`documented` to `executable`. This is **rung 1: timers.** It is unlike the parallel rung: parallel
was a compiler change, but timers need a **new async substrate** — the runtime could display an SLA
`due_at` but nothing *fired*. The highest-value case is the reference model's approve-gate SLA →
Supervisor escalation (`wire-repair-agentic.reference.bpmn`).

Two constructs land, centered on that case:

- **Timer intermediate-catch event** — the process parks for a duration, then auto-proceeds.
- **Interrupting timer boundary on a `userTask` (HITL gate)** — while parked `WAITING_HITL`, an SLA
  timer fires and routes to the boundary's escalation flow.

## Decision

**Extend native, no new infra.** Model the scheduler on the existing startup recovery sweep: a durable
Mongo `timers` collection + a lifespan poller. No RabbitMQ delayed messages, no external scheduler.

- **Substrate.** `timers` rows `{process_instance_id, element_id, kind, fire_at, status, interrupt_id,
  task_id}`, unique on `(instance, element, kind)` so re-registration (crash replay) is idempotent. A
  `TimerService` (injectable clock — the *only* wall-clock read) exposes `register/cancel/due`; the
  poller wakes every `AGENTRT_TIMER_POLL_SECONDS` (default 15) and calls `engine.fire_due(now)`.
  `fire_at` is stored as a native datetime so the `$lte` due-scan is a real temporal comparison.
- **Durations.** `parse_timer` in `amendia_bpmn` (framework-free) resolves ISO-8601 `timeDuration`
  (`PT4H`) / `timeDate` to a `fire_at`. `timeCycle` is recognized but **unsupported** (annotated).
- **Intermediate catch.** New `WAITING_TIMER` instance status (a durable, crash-safe park parallel to
  `WAITING_HITL`; the recovery sweep leaves it alone — the poller resumes it). The catch node
  `interrupt`s with a `kind:"timer"` payload; the engine registers a timer and parks. On fire it
  resumes past the catch.
- **Boundary SLA / escalation.** The compiler layers a conditional edge after the gate: `state.timed_out[T]`
  → the boundary's escalation target, else the normal decision flow. The timer is registered at HITL
  **materialization** (so `due_at` finally *fires*, not just displays).
- **The race — whoever-first wins, guarded by one serialization point.** Both the human decision and
  the timer fire flip the parked instance `WAITING_*→RUNNING` via a guarded transition; the loser is a
  no-op. **Human first:** the decision resumes normally and cancels the timer. **Timer first:** the
  poller resumes with a timeout signal — the node commits *nothing*, records the **timer** as the
  actor, the `HitlTask` is marked **`expired`**, and the process routes to the escalation target; a
  late human decision on the now-`expired` task is rejected (409). Emits `hitl_task_expired` /
  `timer_fired` on the `agent_runtime.*` taxonomy.
- **Profile.** `timers` is appended to `EXECUTION_PROFILES` as the next **cumulative** rung (a `timers`
  runtime also runs `parallel` + `common_subset`). `required_profile(model)` returns `timers` when the
  model has timer constructs; Phase 2.5's derived pin + load-time `>=` guard carry over unchanged — a
  `timers` pack won't load on a lower runtime, refused up front with `pack_requires_profile`. The
  default stays `common_subset`.

## Crash-safety

Timers are durable and the graph checkpoint is durable (MongoDBSaver). On restart the recovery sweep
leaves `WAITING_*` parked; the poller re-scans and fires anything due. A fire is marked `fired` only
*after* the resume segment succeeds, and the instance-status guard makes a re-fire a safe no-op — so a
due timer surviving a restart fires exactly once (no double-escalation).

## Consequences

- SLA `due_at` now actually fires. The reference approve-gate SLA → escalation path executes end to
  end. The webui surfaces a live SLA countdown on the gate and an escalated state once expired.
- The scheduler is a native, dependency-free substrate reused for future timed constructs.

## Limitations (intentionally deferred — assumption noted in code)

- **Timer boundary on a `serviceTask`** (interrupting a mid-flight synchronous capability) — rejected
  under the `timers` profile (`bpmn_timer_boundary_host_unsupported`); only `userTask` gates this rung.
- **`timeCycle` / recurring timers** and **timer start events** — annotated unsupported.
- **Policy-based auto-SLA** without a BPMN boundary — out of scope; escalation is diagram-driven (the
  boundary event defines the path). Concurrent human gates remain sequentialized (ADR-028); the default
  profile is unchanged.
- **Profile hierarchy is a linear cumulative rank.** If independent, non-cumulative capabilities are
  ever needed, generalize to a capability *set* with a subset check (`required ⊆ runtime`) — YAGNI now.
