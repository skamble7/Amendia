# Amendia — Onboarding Wizard Catch-Up Plan

**Purpose:** bring the process-pack onboarding wizard up to the current runtime/contract state. The BPMN
execution engine advanced through ADR-027 → ADR-043 (full Common-Executable + the whole deferred backlog); the
onboarding wizard was last meaningfully updated around ADR-027/032 and now authors at the
serviceTask/userTask/exclusive-gateway level. This plan closes that gap across three tracks, Track 1 (element
coverage) first. Companion to `amendia_process_onboarding_guide.md` (the *what onboarding is*) and the ADR set.

*Grounded against the source on 2026-07-19: `process-registry/app/{models,services,routers}/onboarding.py`,
`app/services/{inference,mcp_introspect}.py`, `webui/src/features/registry/OnboardingWizard.tsx`,
`libs/amendia_contracts/amendia_contracts/process_pack.py`, `libs/amendia_bpmn`.*

## Current state — precisely where the wizard lags

**Already caught up (good news):**
- **BPMN ingestion** does ADR-027 classify-don't-reject (`onboarding.py::_attach_bpmn` — documented/unknown
  tiers, only error-severity findings block). A full reference BPMN with lanes/pools/message-flows is *ingested*,
  not rejected. The old "exclusive-gateways-only" traps are gone.
- **Inference** (`inference.py`) is rich: one pack-local role per named lane (`role.<domain>.<lane>`), pools
  (`is_external`), message flows, capability candidates (all capability-category task kinds + external message
  flows), gateway variables, cross-lane four-eyes SoD candidates, a `decision_capability_candidate` on a
  `businessRuleTask`, and an `external_integration_hint` on message flows.
- **The target is already defined.** The manifest `Binding` contract (`process_pack.py`) already supports the
  full set: `element_kind: Literal[serviceTask|userTask|sendTask|scriptTask|manualTask|businessRuleTask|
  receiveTask|messageCatch|callActivity|…]` and `Executor = CapabilityExecutor | HumanExecutor | MessageExecutor
  | CallExecutor`. Capability kinds are `skill|mcp|llm|deep_agent|decision|reduce`. **The runtime + registry
  validator already execute/validate all of this.** Onboarding just doesn't *author* it yet.

**The lag (three onboarding-only spots):**
1. **`BpmnInventory`** (`models/onboarding.py`) carries only `service_tasks`, `user_tasks`, `gateways`
   (exclusive). No task-kinds, message elements, callActivity, MI markers, compensation handlers, or
   event-subprocess handlers.
2. **The binding rule** (`services/onboarding.py::_set_bindings`) hard-codes serviceTask→capability /
   userTask→human and **rejects** anything else ("not a BPMN service/user task"). `StagedBinding` only models
   `capability|human`. No `message`/`call` executor, no `input_map`/`output_map`, no `message_name`.
3. **Capability *creation* is MCP-only** (`mcp_introspect.py` + `infer_capability`). No path to author the two
   inline-configured kinds `decision` (DMN table) and `reduce` (config); they're reuse-only.
4. **Frontend** (`OnboardingWizard.tsx`, one 1239-line file): `BindingsStep` builds its task list from
   `service_tasks + user_tasks` only and offers capability/human; `CapabilitiesStep` is MCP-introspect only.

**Acceptance target for the whole plan:** onboard `wire-repair-agentic.reference.bpmn` (already a test fixture:
5 serviceTasks, 2 userTasks, a `businessRuleTask`, a `boundaryEvent`, 3 lanes, 3 pools) **end-to-end through
the wizard**, binding every executable element, inferring roles/SoD from lanes — no dumbed-down projection.

---

## A strategic decision to settle first — one fidelity or two?

The onboarding kit split every process into a rich **reference** BPMN and a crippled **executable projection**
*because the parser rejected the rich constructs*. That reason is gone: parallel, timers/SLA/escalation, error
boundaries, message correlation + event gateways, sub-processes, MI, DMN, call activity, compensation all
execute now. So decide:

- **Single-fidelity (recommended):** the reference BPMN *is* the executable one. Lanes/pools/message-flows stay
  as `documented` decoration (used for inference), everything on the sequence flow executes. One artifact,
  hash-pinned. This is the natural end state and what makes Track 1 worth doing.
- **Keep two-fidelity:** only if there's a real reason to run a reduced graph (e.g. a construct genuinely still
  deferred — non-interrupting ESPs, transaction compensation, message-triggered ESPs). Those remaining
  stretches are the only things that would force a projection.

This plan assumes **single-fidelity**; the deferred stretches (recorded in `amendia_bpmn_deferred_backlog.md`)
are the only constructs the wizard should still refuse.

---

## Track 1 — Element-coverage catch-up (the keystone)  ·  ✅ **SHIPPED (ADR-044, 2026-07-19)**

Plumb the onboarding layer up to the `Binding` contract that already exists. No new runtime/validator semantics.

**Shipped:** `BpmnInventory.bindable_elements` (from the model's `bindable_elements()`, containers excluded, with
MI/compensation/ESP/message/call metadata); `_set_bindings` category-validates the full set + refuses containers;
`_compose` emits `MessageExecutor`/`CallExecutor`; inference `executor_type` is category-aware; the wizard
bindings step renders capability/human/message/call sub-forms. Single-fidelity — deferred stretches refused via
existing registry codes at the assemble dry-run. OpenAPI snapshot + `registry.ts` regenerated. *(Note: the
reference fixture's `businessRuleTask` is off-flow → `documented`; the new kinds are covered by synthetic BPMN
tests.)*

**1.1 · Inventory (`models/onboarding.py` + `services/onboarding.py::_attach_bpmn`).** Extend `BpmnInventory`
from `{service_tasks, user_tasks, gateways}` to the full bindable set the parser already classifies, e.g.
`capability_tasks` (serviceTask/sendTask/scriptTask/businessRuleTask), `human_tasks` (userTask/manualTask),
`message_elements` (receiveTask/messageCatch), `call_activities`, plus per-element metadata flags
(`is_multi_instance`, `is_for_compensation`, `compensation_primary`, event-subprocess membership) and the
`callActivity` target hint (`calledElement`+`amendia:calledVersion`). Source it from the `amendia_bpmn` model
(`tasks`, `TASK_EXECUTOR_CATEGORY`, `call_activities`, `multi_instance`, `event_subprocesses`,
`compensations`) — do not re-derive.

**1.2 · Binding rule (`services/onboarding.py::_set_bindings`).** Replace the hard-coded two-kind check with the
real `TASK_EXECUTOR_CATEGORY` map. Add executor types: **`message`** (element_kind ∈ receive/messageCatch,
carries `message_name`, no HITL) and **`call`** (element_kind = callActivity, carries `pack@range` +
`input_map`/`output_map`, no HITL of its own — ADR-039). Extend `StagedBinding`/`InferredBinding` accordingly.
Widen the bijection so the new elements count as bindable (and `isForCompensation` handlers bind like ordinary
capability tasks; the `subProcess`/event-subprocess *containers* are not bound, their inner tasks are). Keep the
side-effect→HITL guard unchanged. **The assemble/dry-run already runs the full 7-stage validator** — it will
validate the richer manifest as-is.

**1.3 · Inference (`inference.py`).** `InferredBinding.executor_type` becomes category-aware (already suggests
`capability`/`human`; add `message` for message elements, `call` for callActivity). The
`decision_capability_candidate` and `external_integration_hint` already exist — thread them so the frontend can
one-click accept (Track 3).

**1.4 · Frontend (`OnboardingWizard.tsx::BindingsStep`).** Build the task list from the full inventory (not
`service_tasks+user_tasks`). Render an executor sub-form per category: capability (as today), human (as today),
**message** (a message-name field), **call** (a callee-pack picker over active packs + an IO-mapping editor:
callee input binding → caller dotpath, and caller artifact → callee output). Show the MI/compensation flags as
badges. Keep the thin/render-session-state pattern.

**1.5 · Cross-cutting.** The onboarding session model gains message/call executor shapes → the **registry
OpenAPI changes** → regenerate `webui/openapi/registry.json` (snapshot test) and `registry.ts` (offline from the
snapshot, as we did for the backlog kinds).

**Decisions to settle for Track 1:** how the `call` callee pack is chosen (recommend: a picker over active packs
in the registry, pinned at commit like a capability); the IO-mapping editor shape; whether MI/compensation
elements are *bindable-only* here or also get a small marker UI (recommend bindable-only first — the markers are
already validated by the runtime).

**Definition of done:** the `wire-repair-agentic.reference.bpmn` fixture onboards through the wizard — the
`businessRuleTask` binds (to a decision or a bound capability), every task kind binds to its correct executor
category, and (if the reference carried them) message/call elements bind. Bijection + dry-run pass on the full
element set. ADR-044 records the catch-up; the onboarding guide §12 matrix + §4 bindings step are updated.

---

## Track 2 — Decision / reduce capability authoring  ·  ✅ **SHIPPED (ADR-046, 2026-07-19)**  ·  *dep: Track 1 (met)*

**Shipped:** `StagedCapability.kind` (mcp|decision|reduce) + inline `table`/`config`; `SetCapabilitiesRequest`
gains `decision_specs[]`/`reduce_specs[]` (same staging transition); inline validation via the shared
`validate_table`/`validate_reduce` (dmn_*/reduce_* as field errors); inferred verdict artifact (output columns →
required, gateway-branchable fields; literal string columns → enum of distinct rule values) / summary artifact
(output_field typed by op). Frontend DMN table builder + reduce builder in the Capabilities step; the Track-3
decision-candidate badge → one-click "author decision table". No new execution/validation semantics.

> **✅ WIZARD CATCH-UP COMPLETE (ADR-044/045/046).** The onboarding wizard now authors everything the runtime
> executes: the full bindable element set + message/call executors (Track 1), lane-persona-driven pre-fills +
> candidate provenance (Track 3), and inline decision/reduce capability authoring (Track 2) — single-fidelity,
> no projection. Original vision delivered.

Add a form-driven path to author the two inline-configured kinds, parallel to MCP introspection.

**2.1 · Backend staging.** `POST /onboarding/{id}/capabilities` (or a sibling) accepts an inline `decision`
config (a normalized DMN table) or `reduce` config, stages a `decision`/`reduce` capability + its output
artifact (reuse the `DecisionRuntime`/`ReduceRuntime` contract + the shared `amendia_bpmn.dmn`/`reduce`
validators for structural checks → surface `dmn_*`/`reduce_*` findings inline). `side_effect` is `read_only`.

**2.2 · DMN table builder (frontend).** A form: input expressions (dotpaths into a bound input artifact) +
types, output columns, rules (bounded unary-test cells: equality/comparison/range/enum/dash), and a hit policy
(UNIQUE/FIRST/PRIORITY/ANY/COLLECT). Emits the inline table. This is the highest-UX-risk control (like the
triage predicate-tree builder) — design it carefully.

**2.3 · Reduce config builder (frontend).** Source list artifact + `item_path` + op (any/all/none/count/
sum/avg/min/max/first/last) + optional per-item predicate (reuse the unary-test control) + output field.

**2.4 · Wire the candidate.** A `businessRuleTask` with a `decision_capability_candidate` hint (already emitted
by inference) offers "author a decision table" inline → stages the `decision` capability → binds it.

**Definition of done:** a business user authors a repairability decision *as a table* in the wizard and binds it
to `Task_AssessRepairability` (or a `businessRuleTask`), no code; a reducer is authorable the same way. ADR-045.

---

## Track 3 — Deepen swimlane / persona UX  ·  ✅ **SHIPPED (ADR-045, 2026-07-19)**  ·  *dep: Track 1 (met)*

**Shipped:** lane-persona→HITL starting defaults (agent→none, analyst→review_after, approver→approve_actions,
supervisor→manual; verb-heuristic fallback; **the side-effect→HITL floor still governs** — a side-effectful
capability is always ≥ approve_actions regardless of lane); persona→`InferredRole.description` seeded into
`role_meta`; SoD/decision candidates surfaced with their rationale as confirmable chips; external message flows →
actionable capability-slot suggestions in the Capabilities step. Enrichment on the existing spine, no new steps,
no contract/validator/runtime change (only `InferredRole.description` added → OpenAPI/`registry.ts` regenerated).

Turn the already-computed inference into low-friction, pre-filled defaults — the original roles/swimlanes
vision, polished.

**3.1 · Lane-driven HITL defaults.** Map lane intent → a suggested HITL mode on `InferredBinding`
(`suggested_hitl_mode` exists; enrich it): an *agent* lane → `none`, an *analyst/reviewer* lane → `review_after`,
an *approver* lane → `approve_actions`, a *supervisor* lane → an escalation target. Heuristic on the lane name +
the task's side-effect classification; always operator-editable.

**3.2 · Persona → `role_meta` pre-fill.** Each named lane becomes a pre-filled pack-local role with a
label/description (the `role_meta` sidecar, ADR-026), so personas flow into the roles the Administration picker
later surfaces.

**3.3 · Pool → external-system scaffolding.** An `is_external` pool + its message flows (already an
`external_integration_hint`) suggests a capability slot ("this flow to *Sanctions Provider* likely needs a
`screen_party` capability") — a nudge toward MCP introspection or reuse.

**3.4 · Surface candidates as one-click accepts.** The SoD candidates (cross-lane draft/approve pairs), the
decision candidate, and integration hints are computed but not actionable — render them as "accept" chips in the
Bindings/Policies steps.

**Definition of done:** onboarding the reference BPMN feels like *confirming inferences* (roles, SoD, decisions,
HITL) rather than filling blank forms — the "progressive disclosure + show provenance" principle from the
original design brief. ADR-046 (or fold into ADR-044 as a UX addendum).

---

## Sequencing & cross-cutting

```
Track 1 (keystone: element coverage) ─┬─→ Track 2 (decision/reduce authoring)
                                       └─→ Track 3 (swimlane/persona UX)
```

- **Track 1 first and alone** — it's the prerequisite; Tracks 2 and 3 both target the element kinds it unlocks.
  Then 2 and 3 in either order (independent).
- **Each track = its own Claude Code prompt** with a recon-first step, same rhythm as the backlog items; ends
  with an ADR + onboarding-guide updates (§4 steps, §10 capability kinds, §12 element matrix).
- **OpenAPI/client:** Track 1 (message/call executor shapes) and Track 2 (decision/reduce staging) change the
  registry contract → regenerate the `registry.json` snapshot + `registry.ts` (offline from the snapshot).
- **Acceptance test across all tracks:** `wire-repair-agentic.reference.bpmn` onboarded wizard-only, activated,
  and run end-to-end via the exception stub (the same E2E you just validated for the projection) — proving the
  single-fidelity reference executes.
- **Guardrail:** the wizard should still refuse exactly the constructs in `amendia_bpmn_deferred_backlog.md`
  stretches (non-interrupting ESPs, message-triggered ESPs, transaction compensation, targeted compensation,
  MI-callee, etc.) — reuse the registry's existing refusal codes; don't invent onboarding-only ones.

## Open decisions (settle as we start each track)
1. **Fidelity:** ✅ **SETTLED — single-fidelity** (2026-07-19). The reference BPMN is the executable one;
   the wizard refuses only the deferred-backlog stretches. Track 1 is being built on this basis (ADR-044).
2. **Track 1 — call binding UX:** callee-pack picker + IO-mapping editor shape; MI/compensation as bindable-only
   vs with marker UI.
3. **Track 2 — DMN authoring surface:** how much FEEL the table builder exposes (stay within the bounded unary
   surface the evaluator supports).
4. **Track 3 — lane→HITL heuristic:** name-based vs an explicit lane-role-intent mapping the operator confirms.

---

*Living plan: Track 1 is the immediate work. When a track ships, strike it here, cite its ADR (044+), and update
the onboarding guide. The end state: the wizard authors everything the runtime executes — a complete reference
BPMN, swimlanes and all, onboarded through forms with no raw JSON and no crippled projection.*
