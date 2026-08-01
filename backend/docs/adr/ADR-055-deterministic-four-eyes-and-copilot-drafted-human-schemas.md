# ADR-055 — Four-eyes is a deterministic invariant; the copilot drafts human-artifact schemas

**Status:** Accepted (2026-07-31)
**Related:** ADR-052 (business-facing onboarding), ADR-054 (stepped pre-filled review), ADR-050 (human-authored
artifacts as dataflow sources), ADR-048 (capability I/O data-flow / input maps), ADR-051 (nameable outputs).

## Context

The onboarding copilot generates a runnable pack from a BPMN diagram + an MCP catalog: the LLM proposes the
semantics, and a deterministic reconciler enforces the invariants ("LLM proposes, engine disposes"). Running two
real processes end-to-end (restaurant, wire-transfer) exposed three places where a *safety* structure was left to
the LLM's discretion, so a normal generation variance produced an unsafe or hollow pack that still passed
validation and activated.

1. **Four-eyes was LLM-dependent.** The human-authored-artifact chain (a human approval task that authors an
   *approved* artifact which the downstream side-effect consumes — the four-eyes gate) only materialized if the LLM
   volunteered `human_authored` outputs and wired them. When it omitted them, the approval task came out hollow (no
   inputs, no outputs): the approver reviewed nothing, produced nothing, and the side-effect applied off the trigger
   regardless of the human decision. Nothing in validation objected, so it went live green. The approve-actions gate
   on the side-effect was also left on the automation/AI lane role (unclaimable by a human), because the approver
   was detected by an "approve HITL mode" signal that real `manual` approval user-tasks don't carry.

2. **Approval gates over-reached.** Once made deterministic, a naive rule gated *every* downstream side-effect a
   human task preceded — so a repair approval spuriously required the downstream *Notify* step to also consume the
   approved repair, raising confusing open questions.

3. **Human-artifact schemas were empty when no tool consumed them.** Schemas were derived only from the fields a
   downstream tool reads (correct for tool inputs, whose closed schemas must not gain invented fields). A
   human-authored artifact with no tool consumer (a terminal decision, e.g. an escalation ruling) therefore rendered
   as a blank form — no baseline for the operator to refine.

## Decision

1. **Four-eyes is a deterministic structural invariant, not an LLM responsibility.** The reconciler detects
   approval gates structurally from signals it already has — a human task that is separation-of-duties-paired with a
   drafting capability (the four-eyes intent, from the inference draft) and is a guaranteed predecessor of a
   side-effectful capability on the flow graph. For every detected gate it *guarantees* the structure: the human
   authors an approved artifact, the side-effect consumes it (materializing the output and rewiring the consumer
   when the LLM omitted them), and the human reviews the draft as read-only context. A hollow approval can no longer
   activate. The human **approver role** is derived from the gate tasks themselves (not from a HITL-mode string), and
   the side-effect's approve-actions gate is reassigned off the automation/AI lane onto that approver (the
   side-effect floor is kept; only the role changes).

2. **A human approval gates only the nearest downstream side-effect.** A gate `(H, S)` forms only when no other
   side-effect lies strictly between `H` and `S`; farther side-effects are gated transitively by the nearest one,
   not by a second consumption of the approval. A human output whose task is **not** a detected gate and gates no
   downstream side-effect is a **terminal record** (e.g. an escalation decision) — it need not be consumed and does
   not block go-live.

3. **The copilot drafts human-artifact schemas; the operator refines.** Human-authored artifact schemas are seeded
   from a union of (a) tool-derived fields — authoritative and required where a consumer actually reads them — and
   (b) an LLM-proposed baseline drawn from whole-process understanding, which fills the gaps and seeds artifacts no
   tool consumes. A human-authored artifact is the person's form, not a tool input, so proposing baseline fields
   there is safe; the tool input-map over-map guard is untouched. The operator refines the result in the ADR-054
   schema refiner, and deterministic validation still gates activation.

## Consequences

- **+** The safety-critical four-eyes structure is guaranteed regardless of LLM variance; a side-effect can never be
  applied without an enforceable human approval, and the gate is always a human role.
- **+** No spurious approval-consumption on downstream side-effects; fewer confusing open questions.
- **+** Human-authored forms start from a sensible baseline instead of a blank, even with no tool consumer.
- **+** Reuses existing machinery — SoD candidates, the flow graph, the schema refiner, version-bump-on-change.
- **−** More deterministic logic in the reconciler (gate detection, materialization, nearest-side-effect scoping) to
  maintain; mitigated by tests over domain-neutral fixtures.
- **−** The LLM baseline can propose fields the operator prunes — acceptable, as it is an explicitly-drafted
  starting point behind the refiner, never authoritative and never on a tool input map.

## Non-goals

- Not changing the runtime, the validator's gating, or the tool input-map safety (the closed-schema over-map guard).
- Not removing the LLM's semantic role — it still proposes executors, dataflow, HITL, and now baseline human
  schemas; the engine enforces the invariants on top.
- Not a domain-specific rule anywhere — every signal (SoD pairs, side-effect flags, guaranteed predecessors, lanes)
  is structural and domain-neutral.
