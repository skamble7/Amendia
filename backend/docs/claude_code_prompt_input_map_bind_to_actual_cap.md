# Claude Code Prompt — `input_map` inference must key off the BOUND capability, not a fuzzy name match

ADR-048 D4 field-level inference works, but only for capability tasks whose **BPMN name token-matches the MCP tool
id**. On the `ws-stan` pack, five tasks still error `unproduced_input` — `Assess`, `DraftReturn`, `Enrich`,
`Notify`, `Screen` — the exact set whose element name diverges from the tool id (`Enrich`↔`enrich_investigation`,
`Assess`↔`assess_beneficiary`, `Screen`↔`screen_party`, `Notify`↔`notify_parties`, `DraftReturn`↔`draft_return`).
The other four (name-matching) get a field-level suggestion. **The capability is already bound on all five rows** —
inference is just failing to use it.

## Root cause

`refine_input_sources` (and the wizard's `resolveInputSources`) re-derive element→capability via the same
name-token Jaccard used for the capability pre-select. When that match fails (divergent BPMN name vs tool id), the
refinement can't resolve the tool's input/output schemas, so it emits **no `input_map`** for that element — even
though the operator has bound the capability. This is the third time this exact name-divergence has bitten
(capability pre-select, then input_map): the systemic fix is to **stop re-guessing the element→capability mapping
and always use the actual binding.**

## Fix — derive the suggestion from the bound `capability_ref`

### 1 · Backend: refine at `set_bindings`, keyed off the real binding (authoritative)
- The element→capability mapping is only a *guess* at `set_capabilities` time (no bindings yet) — keep that as the
  initial hint, but make the binding-time refinement authoritative.
- In `set_bindings` (after each `StagedBinding.capability_ref` is known), compute the field-level `input_map`
  suggestion for every **capability** binding from **its own `capability_ref`** → that capability's declared
  input/output artifact schemas (the descriptor / staged cap), plus the upstream producers' output schemas from
  the BPMN graph. Do **not** re-run the name Jaccard here — the capability is chosen. Populate the binding's
  `input_sources` from this suggestion **only where the operator hasn't already set one** (don't clobber overrides).
- The field-matching logic (input field → upstream output field or trigger path) is unchanged from D4; only the
  *capability resolution* changes from fuzzy-guess to `capability_ref`.

### 2 · Frontend: `resolveInputSources` uses `row.capability_ref`, recompute on change
- `resolveInputSources` must look up the capability IO via **`row.capability_ref`** (the actually-selected ref),
  not `suggestedCapRef`. So a task whose capability was set manually (or by any means) still gets its input-source
  suggestion + "suggested" chip.
- Recompute the suggestion when the operator **changes** a row's capability (so switching the capability re-derives
  the sources), still respecting any source the operator has manually edited.

## Non-goals
- No change to the field-matching heuristic, the ADR-048 contract, the validator, or seed packs. This only fixes
  *which capability's schema* the suggestion is built from — the bound one, not a guessed one.

## Definition of done
- Every capability task — including `Assess`/`DraftReturn`/`Enrich`/`Notify`/`Screen` whose names diverge from
  their tool ids — receives a field-level `input_map` suggestion once its capability is bound, with a "suggested"
  chip; the dry-run shows **zero** `unproduced_input` errors on `ws-stan` with no manual source authoring.
- Changing a row's bound capability re-derives its input sources; operator-edited sources are preserved.
- Tests: a binding whose element name does NOT token-match its `capability_ref` still gets a full field-level
  suggestion at `set_bindings`; the manifest `input_map` is complete for all capability tasks; seed packs
  unchanged. `registry` + `webui` green, `tsc` clean.

## Note (systemic)
Capability pre-select and `input_map` have both now failed the same way — re-deriving element→capability by fuzzy
name. Consider making the **bound `capability_ref` the single source of truth** everywhere downstream of the
Bindings step (any later step that needs "which capability does this element use?" should read the binding, never
re-match by name). Worth a small follow-up sweep.
