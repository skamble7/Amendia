# ADR-034 — Common-Executable finale: collapse to two levels, flip the default, close the arc

**Status:** Accepted · **Date:** 2026-07-17 · **Closes:** the ADR-027 Common-Executable program.
**Builds on:** ADR-027 (strategy) and the construct ladder ADR-028–033 (parallel, timers, error
boundary, messages, sub-process, task kinds).

## Context

The construct ladder is complete: `common_subset → parallel → timers → error_boundary → messages →
subprocess → tasks`. Those granular per-construct profile levels were the **incremental scaffold** —
each rung shipped behind its own level so it could land, be pinned, and be load-guarded independently.
Now that every rung ships together, the scaffold is noise. This phase is **consolidation, not new
constructs**: collapse to the spec's two BPMN conformance levels, **flip the default to
`common_executable`**, prove the whole thing end to end, and correct the now-stale user-facing docs.

## Decision

- **Two levels.** `EXECUTION_PROFILES = ["common_subset", "common_executable"]`. `common_executable`
  covers the entire built set (parallel + timers + error boundary + messages + sub-process + all task
  kinds). `required_profile(model)` collapses to a single check — `common_executable` iff the
  executable core uses **any** beyond-subset construct, else `common_subset`. `compilability_findings`
  keeps every existing finding code: under `common_subset` it refuses all beyond-subset constructs
  (exact Phase-0/1 behavior); the **permanently-deferred** constructs still refuse under *both* levels
  (`callActivity`, sub-process boundary events, timer-boundary-on-serviceTask, inline `<script>`,
  native-DMN inline, event/transaction/ad-hoc sub-process, multi-instance).
- **Migration — no stranded pins.** The retired granular constants are aliases to `common_executable`,
  and `normalize_profile(value)` maps any retired name (`parallel`/`timers`/…) → `common_executable`.
  `parse()`, `compilability_findings()`, `profile_rank()`, and the config field validators normalize on
  the way in, so a persisted `Resolution.required_execution_profile` holding an old granular value, or
  an old `AGENTRT_EXECUTION_PROFILE=timers` env, resolves to the top level. A `common_executable`
  runtime is ≥ every old granular pin, so **nothing pinned earlier fails to load**. Re-activations pin
  only the two current values.
- **Default flip.** `AGENTRT_EXECUTION_PROFILE` and `REGISTRY_EXECUTION_PROFILE` now default to
  **`common_executable`**. Full-BPMN packs activate and run by default; `common_subset` stays selectable
  for a deployment that wants the conservative envelope (it refuses a `common_executable` pack with
  `pack_requires_profile`). The derived pin + load guard are intact — they still matter for such a
  deployment. The seed `common_subset` pack (subset ⊆ executable) activates and runs unchanged; the
  coverage report still marks documentation-only elements (lanes, external pools, message flows) as
  `documented`.
- **No engine changes.** Consolidation is entirely in the profile model + config; HITL/audit/SoD/
  memoization semantics are untouched.

## End-to-end proof (capstone)

A single **full-executable** capstone diagram exercises the whole construct set — an event-based
gateway (message-result vs timer-timeout arm), a business-rule task whose verdict drives an exclusive
gateway, an embedded sub-process containing a parallel fork/join, a send task, a manual-task HITL gate
with an interrupting **SLA timer boundary**, and a service task with an **error boundary** — plus
documentation-only lanes/pools/message-flows. It parses clean, pins `common_executable`, compiles under
`common_executable`, is refused (with each construct's finding) under `common_subset`, and its
documentation-only elements classify `documented`. A composed runtime capstone drives sub-process +
business-rule-verdict-to-gateway + send-task + SLA-boundary + error-boundary end to end under the
flipped default. The seed `wire-repair-standard` still onboards/activates/runs unchanged.

## Consequences

- **The ADR-027 Common-Executable program is complete.** Amendia ingests Full BPMN and executes the
  Common-Executable level by default, classifying the gap honestly.
- Two named levels are the whole surface; the profile machinery (derived pin + `>=` load guard +
  `pack_requires_profile`) still cleanly separates a conservative deployment.

## Standing post-Common-Executable backlog (deferred, not forgotten)

- **`callActivity` / cross-pack composition** — which pack/version is called, IO mapping, pinning (a
  separate design).
- **Native DMN evaluation** — FEEL, hit policies, DMN-file parsing (a `decision`/DMN capability kind or
  an evaluator); today a business-rule task binds a decision capability, `decisionRef` is advisory.
- **Boundary events on a sub-process box** and **timer/message boundary on a serviceTask** (interrupt a
  mid-flight capability).
- **Multi-instance markers**, **compensation / transaction sub-process**, **event / ad-hoc
  sub-process**, **inline `<script>` execution**, **message-throw/send correlation** beyond the inbound
  substrate, **signal / escalation / message-start events**.
- **LLM-agent execution mode** (an autonomous agent as an execution substrate) — an out-of-band track,
  orthogonal to BPMN conformance.
