# Claude Code Prompt — Capability `input_map` (ADR-048): make MCP-per-process packs executable

Implement ADR-048. Today an introspected MCP pack activates with 0 errors then fails at the first node —
`missing required input 'enrich_investigation_input' for element 'Enrich' (have: [])` — because per-tool input
artifacts are never seeded from the trigger and don't chain (each tool emits `<tool>_output`, the next needs
`<tool>_input`). Add an optional, additive **`input_map`** on capability bindings that declares where each input
comes from, resolve it in the runtime, validate the real data-flow, and author it in the wizard. **Stay
domain-neutral** (ADR-047): sources reference the trigger and upstream outputs by name/path only — no envelope
shape hardcoded, no seed/test assumptions.

## Recon first (ground truth)

- `libs/amendia_contracts/amendia_contracts/process_pack.py` — the `Binding` / `Executor` models and the manifest.
  The binding already carries `inputs`/`outputs` (`{name, schema, required}`); call-activity executors already
  carry `input_map`/`output_map` — reuse that shape/vocabulary where sensible.
- `backend/services/agent-runtime/app/engine/task_runner.py` — `_gather_inputs` (asserts `spec.name in
  state["artifacts"]`) and `_run_node` (has `state["envelope"]` + `inputs`, passes both to the executor).
- `backend/services/agent-runtime/app/engine/state.py` — `initial_state` seeds `envelope` + empty `artifacts`.
- `backend/services/agent-runtime/app/engine/executor/mcp_client.py` — builds the `tools/call` `arguments`.
- `backend/services/process-registry/app/validation/pack_validator.py` — the stage-5 IO check that emits
  `unproduced_input` (currently a warning, "assumed seed state").
- `backend/services/process-registry/app/services/onboarding.py::_compose` — emits the binding docs (add
  `input_map` passthrough); `services/inference.py` — where to add the pre-suggestion.
- `webui/src/features/registry/OnboardingWizard.tsx::BindingsStep` — where the operator authors it.

## Change 1 · Contract — add `input_map` to capability bindings (additive)

- Add optional `input_map: dict[str, InputSource]` to the capability `Binding` (contracts). An `InputSource` is one
  of:
  - `{"from": "trigger", "path"?: "<dotpath>"}` — the process trigger payload (today the exception envelope),
    whole or a dotpath into it.
  - `{"from": "artifact", "name": "<upstream_output_name>", "path"?: "<dotpath>"}` — a named artifact an upstream
    binding produced, whole or dotpath.
  - `{"fields": {"<field>": <InputSource>, ...}}` — composite: build an object field-by-field (this is what
    constructs an MCP tool's `arguments` from a mix of trigger + upstream outputs).
- Keep it **optional**: a binding without `input_map` is valid and behaves exactly as today. Regenerate the
  registry OpenAPI snapshot + `webui/src/api/gen/registry.ts`.

## Change 2 · Runtime — resolve inputs through the map (`_gather_inputs`)

- In `_gather_inputs(ctx, state)`: for each declared input `spec`:
  1. if `ctx.input_map` has an entry for `spec.name` → resolve it: `trigger` sources read `state["envelope"]`
     (dotpath via a small resolver — reuse the `expr` dotpath resolver if one exists), `artifact` sources read
     `state["artifacts"][name]` (dotpath), `fields` builds a dict by resolving each field. A referenced upstream
     artifact that is genuinely absent at runtime is an execution error naming the element+source (not a bare
     `KeyError`).
  2. else → **unchanged**: `assert spec.name in artifacts; inputs[spec.name] = artifacts[spec.name]`.
- Thread `input_map` onto `NodeContext` (from the binding). For the `mcp` executor, the resolved inputs become the
  tool-call `arguments` (so `enrich`'s `{envelope, exception_id, reason_codes}` / `assess`'s `{dossier, …}` are
  built from the map). Do not hardcode any field names in the engine — they come from the authored map.
- Seed packs (no `input_map`, shared-name chaining) must be byte-for-byte unaffected — verify an existing seed pack
  instance still runs.

## Change 3 · Validator — the seed-state contract (validate real data-flow)

In `pack_validator.py` stage-5, replace the "assumed seed state" softening with map-aware validation:

- Input mapped `from: trigger` → satisfiable; if a trigger artifact schema is declared (ADR-047), validate the
  dotpath against it; else accept `trigger` as opaque.
- Input mapped `from: artifact` → the referenced artifact MUST be produced by an upstream binding on every path
  reaching this node; else **error** `binding_input_unproduced` (element + input + referenced artifact).
- Input with **no** map entry that is **not** produced upstream → **error** (was the `unproduced_input` warning) —
  it will hard-fail at runtime. Keep a warning only for a genuinely runtime-seeded input if/when such a rule
  exists (none today).
- This must make the current `ws-stan`-shaped pack (per-tool inputs, no map) **fail validation** with element-named
  errors instead of activating and dying at step 1.

## Change 4 · Onboarding compose + inference suggestion

- `onboarding.py::_compose` — pass `input_map` through into the emitted capability binding doc.
- `inference.py` — pre-suggest an `input_map`: the entry capability task (no upstream producer) → its input
  `from: trigger`; a task input whose artifact schema matches exactly one upstream output → `from: artifact` that
  output. Suggestions are hints, fully overridable. Keep the logic generic (graph position + schema match) — no
  domain names.

## Change 5 · Wizard — author `input_map` at the Bindings step

- In `BindingsStep`, for each capability task input, add a small **source picker**: "from trigger (path…)" or
  "from an upstream task's output (task → output, path…)", plus a composite (per-field) mode for multi-field tool
  inputs. Pre-fill from the inferred suggestion (Change 4) with a "suggested" chip; operator overrides. Persist
  into the binding's `input_map`. `tsc` clean.

## Non-goals

- No `output_map` for capability tasks (the output name is the handle; downstream reads it via `input_map`). No
  change to gateway-variable mapping, HITL, or the bijection. No change to seed packs.

## Definition of done

- A capability binding with `input_map` (entry `from: trigger`, later inputs `from: artifact`) runs end-to-end;
  `_gather_inputs` never asserts on a mapped input; the `mcp` executor's `arguments` are built from the map.
- Validation **errors** (element-named) on: an unmapped-and-unproduced input; an `input_map` referencing an
  artifact no upstream binding produces. A current `ws-stan`-shaped pack fails validation instead of activating.
- Seed packs (no `input_map`) validate and run exactly as before (regression-tested).
- Tests: contract round-trip of `input_map`; runtime resolution for `trigger`/`artifact`/`fields` + the
  missing-upstream execution error; validator errors for the two cases above; an inference test for the entry→
  trigger and schema-match→output suggestions; a `BindingsStep` render/author test. OpenAPI snapshot + `registry.ts`
  regenerated. Onboarding guide §4 (Bindings) documents input sourcing. ADR-048 referenced.
