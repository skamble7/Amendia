# ADR-033 — Task-kind coverage: BPMN task → executor category (Common-Executable ladder rung 5, final construct)

**Status:** Accepted · **Date:** 2026-07-17 · **Builds on:** ADR-027 through ADR-032, Phase 2.5
(per-pack profile pin + load guard).

## Context

The **last construct rung** of the Common-Executable ladder. It makes the remaining standard BPMN
task types executable — and it is small, because each maps onto an **executor Amendia already runs**.
There is essentially **no new runtime engine code**: the work is a task-kind → executor-category
mapping, plus validation, promotion, and honest deferrals for real DMN / inline scripts.

## Decision

**One shared `TASK_EXECUTOR_CATEGORY` map** (in `amendia_bpmn`) drives everything — validation and
compilation treat a task by its executor **category**, not its BPMN tag, so adding a task kind is a
one-line change:

| BPMN task | Executor category | Notes |
|---|---|---|
| `serviceTask` | capability | (existing) |
| `userTask` | human (HITL) | (existing) |
| `receiveTask` | message | (Phase 2.4) |
| `sendTask` | capability | the bound capability performs the send; `side_effectful` → `approve_actions` floor (existing guard) |
| `scriptTask` | capability | a bound *skill* capability computes; an inline `<script>` body is **not executed** |
| `manualTask` | human (HITL) | a human performs it offline; default `hitl.mode = manual` |
| `businessRuleTask` | capability | a bound *decision* capability returns a verdict artifact; native DMN **deferred** |

- **Parser / model (2.7.a).** `TASK_KINDS` extended to the full set; the four new kinds are `documented`
  by default and **promoted to `executable` under the `tasks` profile** (like every prior construct).
  `businessRuleTask`'s `decisionRef`/`calledDecision` is captured as **advisory** metadata (inference
  only). A **fully-isolated** floating task (no incoming/outgoing flow) is reclassified `documented`
  (decoration) rather than becoming a false unreachable-node error — mirroring wired-vs-documented for
  boundary events, preserving ADR-027's "classify, don't reject".
- **Validation (2.7.b).** `Binding.element_kind` extended to the full task set; the registry bijection's
  executor-kind check is driven by `TASK_EXECUTOR_CATEGORY` (the same check generalized from the old
  serviceTask→capability / userTask→human pair). The side-effect→HITL guard is unchanged — a `sendTask`
  on a `side_effectful` capability still requires `approve_actions`. The (recursive, post-2.6) bijection
  covers nested new-kind tasks automatically.
- **Compiler / executor (2.7.c).** **No new executor.** A task node is resolved by its executor
  category via the existing `make_task_node`: capability-category → the capability node runner;
  `manualTask` → the human/HITL path (`manual`); `receiveTask` → the message path (2.4). Everything
  downstream (artifact validation, SoD, memoization, a gateway branching on a `businessRuleTask`'s
  verdict artifact) works unchanged because these are ordinary capability/human nodes.
- **Profile (2.7.d).** `tasks` appended to `EXECUTION_PROFILES` as the final cumulative rung (above
  `subprocess`); `required_profile` returns it when the executable core uses the new kinds; Phase-2.5
  pin + load-guard carry over. Default stays `common_subset`.
- **Inference / coverage (2.7.e).** Inference scaffolds bindings across the full task set by category
  (send/script/businessRule → capability candidate, manual → human `manual`), only for **connected**
  tasks; a `sendTask` is annotated side-effectful and a `businessRuleTask` "bind a decision capability
  (native DMN not evaluated)". Coverage/webui show the kinds executable under the profile.

## Consequences

- All standard BPMN task types are bindable and executable, each routed to an existing executor
  category via one map — **no new executor engine**. A `businessRuleTask` runs via a bound decision
  capability and its verdict drives a downstream gateway (proven end to end).
- **This completes the Common-Executable construct set.** The next phase (2.8) is *consolidation* —
  collapsing the per-construct profile levels into a single `common_executable` alias — not a new
  construct.

## Deferrals (the honest edge)

- **Native DMN evaluation.** A `businessRuleTask` executes via a *bound capability*, not an embedded
  DMN decision-table engine (no FEEL, hit policies, or DMN-file parsing). Real DMN is a **separate
  feature track** (a `decision`/DMN capability kind or a DMN evaluator), not a Common-Executable
  conformance blocker. The `decisionRef` is captured for inference only.
- **Inline `scriptTask` code.** An embedded `<script>` body is **not executed** (arbitrary code
  violates the capability/audit model); a `scriptTask` must bind a skill capability. An inline body is
  refused with `bpmn_inline_script_unsupported`.
- **Send/receive correlation** beyond Phase 2.4; no new message semantics here. No new async substrate,
  no concurrent human gates, no default-profile change.
