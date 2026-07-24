# Claude Code Prompt — ADR-048 D4 follow-through: make `input_map` inference actually land, field-level

ADR-048 shipped, but on a real MCP pack the input-source inference produces **nothing**: every capability task's
picker shows the default "from trigger", `input_sources` is empty on save, `_compose` emits no `input_map`, and
all N capability inputs error as `unproduced_input`. Fix the inference→pre-fill→persist chain **and** upgrade the
inference from coarse whole-artifact to **field-level**, so the operator confirms a suggestion instead of authoring
each source by hand. Stay domain-neutral (ADR-047) — sources are graph/schema-derived, never domain names.

## Recon / confirm the break (do this first)

- `services/inference.py` (~152-180): `suggested_input_source` = `{from:trigger}` (entry) / `{from:artifact,
  element:<up>}` (downstream, nearest upstream capability). Confirm it's set on every capability binding and
  **serialized to the frontend** (in the registry OpenAPI snapshot + `webui/src/api/gen/registry.ts`). A missing
  field here makes `resolveInputSources` see `undefined` and bail.
- `OnboardingWizard.tsx::resolveInputSources` (~1131): bails to `{}` when `!sug || !io || !io.input`, where
  `io = capIO[suggestedCapRef[...].bareId]` and `capIO` is built from `staged_capabilities[].input_name/
  output_name`. Confirm **introspected MCP caps carry `input_name`/`output_name`** — if they're empty, every
  resolve returns `{}`. Also confirm the pre-filled `input_sources` is (a) written for existing rows too (not only
  brand-new ones), and (b) actually included in the Bindings **save payload** so it round-trips into
  `StagedBinding.input_sources` → `_compose` → manifest `input_map`.

Whatever in that chain drops the value, fix it so a confidently-inferred source **persists to the manifest**.

## Change 1 · Field-level inference (backend)

Replace the whole-artifact suggestion with a per-input-field map. For each capability binding, in BPMN topological
order, using the tool's **input schema** (the introspected `<tool>_input` artifact's properties) and the set of
**upstream output** artifact schemas reachable on the flows into this node:

- **Entry capability task** (no upstream capability producer): map each input field `from: trigger` — the whole
  trigger for a field that is the payload itself, and a dotpath (`{from:trigger, path:"<field>"}`) for scalar
  fields whose name exists on the trigger schema (e.g. `exception_id`, `reason_codes`). Leave a field unmapped
  (blank, for the operator) only if no confident trigger source exists.
- **Downstream task**: for each input field, pick the best source by **name + type match** against (a) upstream
  output fields → `{from:artifact, name:<that output>, path:<field>}`, then (b) trigger fields → `{from:trigger,
  path:<field>}`. Accept only a confident match (exact/near name + compatible type); otherwise leave it for the
  operator. Emit a composite `{fields:{…}}` when the input has >1 field, or a single source when it's a passthrough.

Expose this as the binding's `suggested_input_source` (now a full/partial `input_map`, not a one-key hint). Keep it
generic — decisions come from graph position + schema field names/types, never domain literals. Regenerate the
OpenAPI snapshot + `registry.ts`.

## Change 2 · Pre-fill, persist, and show it (wizard)

- Initialize each capability row's `input_sources` from the (now field-level) suggestion for **both** new and
  existing rows; render a **"suggested"** chip on each pre-filled field (mirroring the capability pre-fill). The
  operator overrides via the existing `SourcePicker` (trigger/artifact/composite).
- Ensure `input_sources` is in the Bindings save payload so it reaches the manifest. A field left with no
  confident suggestion shows the empty picker (the operator must set it) — and the validator's
  `unproduced_input`/`binding_input_unproduced` error still guards it, so nothing silently ships unmapped.

## Change 3 · Runtime arg-shape (verify, fix if needed)

Confirm `_mcp_arguments` builds the tool-call `arguments` as the **resolved composite object** the tool expects
(`{dossier:…, exception_id:…, reason_codes:…}`), i.e. the field-level `input_map` resolves into the tool's input
shape — not the whole upstream artifact under a single key. Add a test if this path isn't covered.

## Non-goals / honest limits

- Field matching is heuristic (name + type). Where a tool input field has no clear producer, inference leaves it
  blank for the operator — it does not wild-guess. Inference should confidently cover the common cases (the
  dominant upstream output + obvious trigger scalars); the operator confirms the rest. No output_map, no change to
  the ADR-048 contract or the validator's error semantics.

## Definition of done

- Opening Bindings on an introspected MCP pack shows each capability task's input **pre-filled** with a field-level
  source (entry from trigger; downstream from the matched upstream output + trigger scalars), each with a
  "suggested" chip; the operator changes only disagreements. The suggestion **persists** — the manifest carries a
  real `input_map`, and the dry-run has **zero** `unproduced_input` errors without manual entry (for the confidently
  matched fields).
- The re-onboarded `ws-stan` pack (with `approve_actions` + inferred `input_map`) validates clean and runs
  end-to-end: `Enrich` sources from the trigger, `Assess` sources `dossier` from `enrich_investigation_output`, etc.
- Tests: entry-task field-level trigger inference; downstream `dossier←upstream output` + `exception_id/
  reason_codes←trigger`; suggestion persists to `_compose`→manifest `input_map`; `_mcp_arguments` builds the correct
  composite; an unmatched field is left blank and still guarded by the validator. OpenAPI snapshot + `registry.ts`
  regenerated; onboarding guide §4 updated. No new ADR (this is ADR-048 D4 realized).
