# ADR-050 — Human-authored artifacts as first-class data-flow sources

**Status:** Accepted — shipped 2026-07-27
**Date:** 2026-07-27
**Context owner:** Sandeep Kamble
**Relates:** ADR-048 (capability-IO `input_map`), ADR-049 (declared trigger artifact + contracts eviction),
ADR-047 (platform domain-neutrality; the pack's declared trigger artifact), ADR-025 (the `OnboardingSession`
state machine), ADR-031/039 (message / call executors), the Process Onboarding Guide + the Restaurant Dine-In
worked example.

> Reconstructed from the shipped implementation. Replace with the canonical project-doc body if it differs.

## Context

ADR-048 made a capability binding's inputs sourceable from the trigger or an **upstream capability output**,
and ADR-049 made the trigger a first-class, operator-declared artifact. One data-flow origin was still
second-class in **onboarding**: the artifact a **human** task produces.

The **runtime** already supports human-produced artifacts. In the seeded wire packs, the human `Task_ObtainInfo`
produces `info_resolution`, which `assess_beneficiary` (a capability) consumes — a hand-authored manifest where
a human binding carries `outputs` and a downstream capability's `input_map` resolves a `{from: artifact}` source
to that human output. But the **wizard could not author this**:

1. **A human/message binding could not declare an output.** `set_bindings` mirrored `inputs`/`outputs` only for
   a **capability** (from `_capability_io_and_policy`); a human/message/call binding always got `outputs: []`.
   The request DTO (`BindingInput`) had no `outputs` field at all.
2. **There was no home for an operator-authored artifact schema.** The only artifacts a session held were
   introspected tool I/O (`staged_artifacts`, rebuilt wholesale by `set_capabilities`) and the declared trigger
   (`trigger_artifact`, ADR-049). A schema that is **neither** — e.g. `art.dining.order`, the shape a waiter's
   order form produces — had nowhere to live.
3. **The "upstream outputs available to a capability input" set was capability-only.** Both the inference
   suggestion (`inferred.upstream_caps` → `_refine_binding_input_sources`) and the graph walk (`_upstream_caps`)
   collected only capability elements, so a human task's output could never be *offered* as a from-artifact
   source in the wizard.

The result: a pack like restaurant dine-in — where a **human** takes the order and a chain of capabilities
validate / screen / bill / fire off that human-authored `order` — could be **seeded** but not **onboarded via
the wizard**. This ADR closes that onboarding gap. It is **onboarding-only**: the manifest shape, the runtime,
and the validator's data-flow resolution were already general.

## Decision

### D1 — Operator-authored artifacts are first-class staged artifacts

- A new session field `OnboardingSession.authored_artifacts: List[StagedArtifact]` holds artifact schemas that
  are **neither** a tool's I/O **nor** the trigger (`art.<domain>.<name>`, e.g. `art.dining.order`,
  `art.dining.payment_retry`). It is kept **apart** from `staged_artifacts` — which `set_capabilities` rebuilds
  wholesale from introspection — so re-staging capabilities never drops an authored artifact.
- A **declare-artifact** action mirrors ADR-049's declare-trigger: `PUT /onboarding/{id}/artifacts` with
  `DeclareArtifactRequest{artifact_key, version, title, description?, json_schema}`. It validates the id
  (`art.<domain>.<name>`, lowercase) and an object schema with a `properties` map, **upserts** by key, and
  clears only the dry-run (adding an artifact never invalidates bindings by itself). Callable once the process
  is known (≥ `bpmn_attached`) — an enrichment, not a state step.
- At assemble, `_compose` **registers** each authored artifact like any staged schema (deduped by key against
  staged + trigger) and lists it among the pack `artifacts`.

### D2 — A human (and message) binding may declare its outputs

- `BindingInput` gains `inputs`/`outputs` (`StagedBindingIO{name, schema_ref, required}`); `StagedBinding`
  already carried them. `set_bindings` now accepts them **for a human / message executor** and validates:
  each `schema_ref` must resolve to a **staged, authored, or trigger** artifact; names are unique within the
  binding; and a **human/message output name is unique across the whole run** (a `{from: artifact, name}` source
  addresses a produced artifact by name, so a collision would be ambiguous). Capability outputs stay mirrored
  from the capability (and legitimately repeat when one capability is bound to several elements — never flagged).
- `_compose` emits each binding's `outputs` into the manifest `Binding.outputs` (its `schema_ref`s already land
  among the pack `artifacts`). A `call` binding is unchanged — it declares IO via its `input_map`/`output_map`.

### D3 — Human / message / call outputs are included in the upstream-producer set

- Inference generalizes `_upstream_caps` into `_upstream(elem, stop_ids)` and adds `producer_ids` (capability
  **plus** human/message/call) and a new `InferredBinding.upstream_producers` — the nearest-first producer set,
  a **superset** of `upstream_caps` (capabilities still lead the coarse suggestion).
- `_refine_binding_input_sources` unions `upstream_caps` with `upstream_producers`, relaxes the producer filter
  from "capability only" to **"any producer with a declared output"**, and includes authored + trigger schemas
  when matching input fields — so a capability input **auto-sources** from a human-authored artifact, and a
  `{from: artifact}` source **resolves** to a human output.
- `PackValidator` needed no change: its stage-5 `producers` set was already keyed off **every** binding's
  `outputs`, so a from-artifact input mapped to a human output validates cleanly once emitted.

### D4 — The wizard surfaces it (webui)

- A **human/message** binding renders an **Outputs** section (mirroring the capability input-source section):
  the operator declares each output as a **name + a staged/authored/trigger artifact schema**, choosing an
  existing artifact or **authoring a new one inline**. The ADR-049 "declare trigger schema" panel is generalized
  into a reusable **"author an artifact schema"** affordance shared by both.
- The SourcePicker's "upstream output" list is extended from capability outputs to **every** task's declared
  output, so a downstream capability input can be sourced from e.g. `order (Task_TakeOrder)`.

## Consequences

- **The restaurant dine-in pack onboards end-to-end.** Declare `art.dining.order` + `art.dining.payment_retry`;
  bind `Task_TakeOrder` / `Task_ReviseOrder` to produce `order` and `Task_ResolvePayment` to produce
  `payment_retry`; then `Task_ValidateOrder` / `Task_ScreenAllergens` / `Task_GenerateBill` / `Task_FireTicket`
  source `order` from the **human** output (not the trigger), and `Task_ProcessPayment`'s `tender` sources
  `payment_retry` from `Task_ResolvePayment` — the same human-authored-precedence pattern that terminates the
  wire needs-info loop, now authored in the wizard.
- **The wire pack is unchanged.** It is seeded (a hand-authored manifest, not onboarded), and its human-output
  shape already validated; no seed, contract, or runtime code changes.
- **Backward-compatible.** `authored_artifacts` and a binding's `outputs` default empty; a capability-only pack
  onboards exactly as before, and a pre-ADR-050 session (no `upstream_producers`) falls back to `upstream_caps`.
- **Data-flow is now origin-complete.** A capability input can be sourced from the **trigger** (ADR-049), an
  **upstream capability output** (ADR-048), or a **human/message-authored artifact** (this ADR) — the three
  origins a running process actually has.
