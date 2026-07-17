# ADR-030 — Error boundary events: modeled rejection paths (Common-Executable ladder rung 2)

**Status:** Accepted · **Date:** 2026-07-17 · **Builds on:** ADR-027 (BPMN conformance / execution
profiles), ADR-028 (parallel spike + ladder shape), ADR-029 (timers rung + boundary-edge machinery),
Phase 2.5 (per-pack profile pin + load guard).

## Context

This is **rung 2** of the Common-Executable ladder. Unlike timers (ADR-029) it needs **no async
substrate** — an error boundary is *synchronous* (a task's own capability signals a business error on
the way out) and it **reuses the boundary-edge machinery from Phase 2.2.d**.

Today any capability error routes the instance to `FAILURE_SINK` → `process_failed`. But a BPMN error
boundary event models a **business** error (payment rejected, screening hit, insufficient info) as a
*first-class branch* — distinct from a **technical** failure (timeout, crash, bug). This rung adds
that distinction so a modeled business error becomes a routed rejection/rework path instead of a dead
instance — delivering the reference model's `ApplyRepair → "payment rejected"` boundary.

## Decision

**Business vs technical error, split at the exception type.**

- **`CapabilityBusinessError(error_code, detail)`** (executor layer) signals a *modeled* outcome. The
  capability-execution core re-raises it unwrapped; **every other exception stays a technical failure**
  (`CapabilityError`) and takes the existing fail/retry path unchanged. The task-node wrapper catches
  only `CapabilityBusinessError` and turns it into a boundary-route state delta. (Simulation: the
  wire-repair `apply_repair` sim raises `PAYMENT_REJECTED` under an `RJCT` steer. **Real `llm`/`mcp`
  business-error mapping is deferred** — see below.)

- **Parse/promote.** The executable parser now retains, per host task, its error boundary events
  `{id, error_code, target}` — `error_code` from `errorRef → <bpmn:error errorCode>`, or `None` for a
  catch-all (no `errorRef`). Only *wired* boundaries (with an outgoing flow) are execution constructs;
  an unwired one stays `documented`. Reachability is augmented (host → target) so a rework/return node
  reached only via the boundary is not a false "unreachable". Error boundaries attach to
  `serviceTask`s (and `userTask`s) — synchronous, so no "interrupt a mid-flight task" problem.

- **One unified boundary channel.** The Phase-2.2.d timer-only `timed_out[T]` flag is generalized into
  a single `ProcessState.boundary` channel: `{element_id: {"kind": "timer"} | {"kind": "error",
  "code": C}}` (dict-merge). The post-node conditional edge reads `boundary[T]`:
  `timer` → the timer target (2.2.d, unchanged); `error,C` → the boundary whose `error_code == C`, else
  a catch-all, else **`FAILURE_SINK`** (an *unmodeled* business error is still a failure, its code in
  `last_error`); none → the normal outgoing flow. All ADR-029 timer tests stay green through the refactor.

- **Stays running.** On a business-error route the `actor_log` records the capability as actor with the
  `error_code`; the instance proceeds to the boundary target and does **not** emit `process_failed`.

- **Profile.** `error_boundary` is appended to `EXECUTION_PROFILES` as the next **cumulative** rung
  (above `timers`). `required_profile(model)` returns it when the executable core has error boundaries;
  Phase-2.5's derived pin + load-time `>=` guard carry over — such a pack won't load on a lower runtime
  (refused with `pack_requires_profile`). `compilability_findings` accepts error boundaries under the
  profile and validates them (no duplicate `error_code` per host, at most one catch-all). Default stays
  `common_subset`.

## Consequences

- A capability can signal a modeled business error; the runtime routes it to the matching (or catch-all)
  boundary flow, instance still running, while technical failures still fail — the reference
  `ApplyRepair → payment-rejected` rework path runs end to end.
- The boundary router is now one channel serving both timer and error boundaries; future boundary kinds
  (signal, escalation, message) slot into the same `boundary[T].kind` dispatch.

## Deferred / non-goals

- **BPMN compensation** (`compensateEventDefinition`, compensation handlers, compensate-throw) — true
  undo semantics are a separate, larger design. This rung is error boundary → a *routed*
  rejection/rework path only.
- **Real `llm`/`mcp` business-error mapping** — the mechanism + simulation is this rung. Follow-up: map
  a structured-output field / MCP `isError` result → an `error_code` so a real capability can raise
  `CapabilityBusinessError`.
- **Escalation / signal / message boundary events** — later rungs. No concurrent human gates; no
  default-profile change.
- The cumulative-linear-rank assumption (ADR-029) still holds; the profile levels will likely collapse
  toward a single `common_executable` alias once the construct set is complete — YAGNI to generalize to
  capability-sets now.
