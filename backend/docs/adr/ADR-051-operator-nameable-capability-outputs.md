# ADR-051 — Operator-nameable capability outputs (gateway-condition alignment)

**Status:** Accepted — shipped 2026-07-27
**Date:** 2026-07-27
**Context owner:** Sandeep Kamble
**Relates:** ADR-027 (gateway variables + schema-aware validation), ADR-048 (capability-IO `input_map`),
ADR-049/050 (declared trigger + human-authored artifacts as data-flow sources), ADR-033 (executor categories),
the Process Onboarding Guide + the Restaurant Dine-In worked example. Foundational for a future LLM-assisted
onboarding copilot (naming outputs to match design intent).

> Reconstructed from the shipped implementation. Replace with the canonical project-doc body if it differs.

## Context

The runtime resolves a gateway's BPMN condition dot-path against `state.artifacts`, **keyed by each binding's
output name** (`agent-runtime/app/engine/expr.py` + `task_runner.py` — the task runner returns
`{binding_output_name: data}`): `validation.order_verdict` → `artifacts["validation"]["order_verdict"]`.
`gateway_variables` in the manifest is validation/documentation metadata; the runtime evaluates the BPMN
condition **directly** against output names.

The seed packs work because their hand-authored manifests use **semantic output names** —
`Task_AssessRepairability`'s output is named `beneficiary`, matching the condition `beneficiary.repair_verdict`.
But the **wizard forces** capability output names to `<tool>_output`
(`mcp_introspect.infer_capability`: `out_name = sanitize_name(tool) + "_output"`). So a wizard-onboarded
`Task_ValidateOrder` produces `validate_order_output`, which can **never** match a designer's condition
`validation.order_verdict` → the gateway resolves to nothing and always takes its default branch, silently.

The restaurant pack surfaced this (three gateways that never branch); the wire pack hid it (hand-seeded with
semantic names). It is the same class of gap as ADR-049/050: **the wizard cannot express something the runtime
and the manifest already support** — the manifest's `Binding.outputs[].name` has always been free-form.

## Decision

### D1 — A capability binding's output name is settable

- `BindingInput` gains `output_name: Optional[str]` — a settable name for a **capability** binding.
  `set_bindings` renames the mirrored output (`StagedBindingIO.name`) with it; the artifact **`schema_ref` is
  unchanged** (only the addressable name changes). It is emitted into the manifest `Binding.outputs[].name`.
- Human/message outputs (ADR-050) are unaffected — they already declare their own names; `call` bindings use
  their `input_map`/`output_map`. `mcp_introspect.infer_capability` still produces `<tool>_output` as the
  staged **default**; the settable name overrides it at the binding layer.

### D2 — Smart default from the gateway it feeds (deterministic, no LLM)

- Inference (`infer_draft`) computes `InferredBinding.suggested_output_name`: for a capability task
  **immediately upstream** of an `exclusiveGateway` that carries a condition, the gateway condition's **first
  segment** (`validation` from `validation.order_verdict`; likewise `allergen`, `receipt`). Derived purely from
  graph position + condition text.
- `set_bindings` applies the default with precedence **operator-set `output_name` → inferred
  `suggested_output_name` → `<tool>_output`**. So the common case (a capability that feeds a gateway) is
  **zero-touch**: its output auto-names to what the condition reads, and the gateway branches.

### D3 — Stage-6 validates the condition against output names

- For a conditional `exclusiveGateway` **not** covered by an authored `gateway_variables` entry, Stage-6 reads
  the raw condition (runtime truth) and requires its first segment to be a **produced upstream binding output**
  carrying the required decision field — emitting `gateway_condition_unproduced` /
  `gateway_condition_field_not_required`. This turns today's silent "gateway never branches" into an
  **authoring-time error**. Gateways with an authored `gateway_variables` entry keep the existing
  `gateway_variable_*` checks (so the seed packs' behaviour is unchanged).

### D4 — The wizard surfaces it

- A capability binding renders an editable **Output name** field, pre-filled by the default (a "from gateway"
  chip marks the gateway-derived one). The upstream-output picker (`allOutputs`) and the input-map suggestion
  reflect the **chosen** name, so a downstream `{from: artifact}` source matches what the binding emits. The
  inferred gateway-variable's first segment and the auto-named output line up by construction (both derive from
  the same condition first segment).

## Consequences

- **Wizard-onboarded packs satisfy designer-authored gateway conditions with no BPMN hack.** The restaurant
  pack's `validation` / `allergen` / `receipt` align with `Gateway_OrderOK` / `Gateway_AllergenClear` /
  `Gateway_PaymentOK`, and the three gateways branch at runtime.
- **The reference BPMN stays clean** (semantic conditions, not `<tool>_output`) — a better teaching example, and
  the wire pack is unchanged (seeded with semantic names; its gateways carry authored `gateway_variables`).
- **Backward-compatible.** `output_name` defaults empty; a capability that feeds no gateway keeps
  `<tool>_output`; a pre-ADR-051 session (no `suggested_output_name`) falls back to the tool default. Capability
  inputs are untouched.
- **Foundational for LLM-assisted onboarding.** A copilot (or the operator) can name outputs to match design
  intent; without a settable name, neither can.
