# ADR-044 — Onboarding element-coverage catch-up (single-fidelity authoring)

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-027 (classify-don't-reject ingestion +
the inference draft), ADR-031/033/039 (the message / full-task-set / callActivity **manifest** contracts —
already shipped), ADR-035→043 (the execution ladder the runtime already runs). **Track:** Onboarding Track 1
(the keystone) — bring the *authoring wizard* up to the element set the runtime already executes.

## Context — the lag was onboarding-only

The manifest **`Binding` contract and the runtime were already fully caught up**: `Binding.element_kind` is a
`Literal` over the whole standard task set + `messageCatch`/`receiveTask` + `callActivity`, `Executor =
CapabilityExecutor | HumanExecutor | MessageExecutor | CallExecutor`, and the 7-stage validator + compiler run
all of it. Only the **onboarding layer** still assumed two kinds — it built the inventory from `service_tasks`
+ `user_tasks`, hard-coded `serviceTask→capability` / `userTask→human`, and rejected anything else. So a diagram
using a `businessRuleTask`, `sendTask`, a message `receiveTask`, or a `callActivity` could execute but **could
not be authored** through the wizard. This task plumbs onboarding up to the existing target; it invents **no**
execution or validation semantics.

## Decision — SINGLE FIDELITY

**The reference BPMN *is* the executable one.** Lanes / pools / message-flows are `documented` decoration used
for inference; **everything on the sequence flow executes**. There is no separate "executable projection" to
upload. The wizard refuses **only** the constructs still deferred in the BPMN backlog (non-interrupting /
message-triggered event sub-processes, transaction / targeted / multi-instance compensation, MI callee, …) —
and it does so via the **existing registry refusal codes** at the assemble dry-run, not new onboarding-only
gates.

### 1 · Inventory — the full bindable set (from the parsed model, not re-derived)

`BpmnInventory` gains an authoritative `bindable_elements: List[BindableElementSummary]`, sourced directly from
the parsed `amendia_bpmn` model's `bindable_elements()` (the full task set + message elements + callActivity;
the `subProcess` / event-subprocess **containers** are never in it). Each row carries its `category`
(`TASK_EXECUTOR_CATEGORY`), specific `element_kind`, and the badges the binding UI needs — `is_multi_instance`
(ADR-036), `is_for_compensation` + `compensation_primary` (ADR-043), `in_event_subprocess` (ADR-042),
`message_name` (message elements), `called_pack` / `called_version` (callActivity). `service_tasks` /
`user_tasks` are retained as legacy serviceTask-only / userTask-only views (a strict subset — markers, coverage
groups).

### 2 · Binding rule — bijection + category over the full set

`set_bindings` validates each binding's `executor_type` against the element's category (mirroring the contract's
`Binding._executor_matches_kind`): capability/human keep the side-effect→HITL guard; **message** elements bind a
`message` executor with a `message_name` and **no HITL**; a **callActivity** binds a `call` executor with a
callee `pack`/`version` + `input_map`/`output_map` and **no HITL of its own** (ADR-039). The bijection now spans
the full bindable set (including `isForCompensation` handlers, which bind like ordinary tasks); the
`subProcess`/ESP **containers** are excluded (a binding for one is refused). Deferred stretches are **not**
refused here — the assemble dry-run's existing compilability + cross-contract stages surface them with their
existing codes.

### 3 · Manifest composition — the right Executor per binding

`_compose` emits the correct `Executor` union member per staged binding — `CapabilityExecutor` /
`HumanExecutor` as before, plus `MessageExecutor{message_name}` and `CallExecutor{pack, version, input_map,
output_map}` — and omits `hitl` for message/call. The dry-run runs the **unchanged** 7-stage validator over the
composed manifest.

### 4 · Inference + frontend

`InferredBinding.executor_type` is category-aware (adds `message`/`call`); the existing
`decision_capability_candidate` / `external_integration_hint` / SoD-candidate outputs are already produced
(Track 3 consumes them). The wizard's bindings step renders an executor sub-form per category — capability /
human (as before), **message** (a message-name field), **call** (an active-pack picker + an IO-map editor) —
with `multi-instance` / `compensates` / `event-subprocess` badges, keeping the server-driven errors + inferred
pre-fill.

## Consequences

- The onboarding inventory, bindings, and wizard now author the **full bindable element set** the runtime
  executes, producing the existing manifest `Binding`/`Executor` contract — single fidelity, no projection. A
  `businessRuleTask` / `sendTask` / message `receiveTask` / `callActivity` onboards; the `subProcess`/ESP
  containers stay unbound; only the backlog's deferred stretches are refused (existing codes). The registry
  OpenAPI snapshot + `registry.ts` are regenerated (additive: `bindable_elements` + message/call binding
  fields). No contract-model or runtime change; the projection + standard packs onboard byte-unchanged.

## Non-goals (later tracks)

- **Decision / reduce authoring** (Track 2) — a `businessRuleTask` here binds an existing/reused capability.
- **New lane→HITL heuristics / one-click candidate UX** (Track 3) — the inference outputs are made available,
  not yet surfaced as guided actions.
- No new execution/validator semantics — the contract + validator already cover this.
