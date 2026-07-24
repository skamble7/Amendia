# ADR-048 — Capability-IO data-flow mapping (`input_map`) and the validator↔runtime seed-state contract

**Status:** Accepted — shipped 2026-07-21
**Date:** 2026-07-21
**Context owner:** Sandeep Kamble
**Relates:** ADR-024 (self-descriptive capability descriptors), ADR-027 (ingest→execute conformance), ADR-047
(platform domain-neutrality / generic trigger artifact), the MCP Implementor Guideline.

## Context

The MCP-per-process onboarding (introspect a tool → one input artifact from its `inputSchema`, one output
artifact from its `outputSchema`, one `mcp` capability) produces packs that **validate and activate but fail at
the first node at runtime**. Observed: `ws-stan@1.0.0` activated with 0 errors, then every instance failed
immediately with:

```
missing required input 'enrich_investigation_input' for element 'Enrich' (have: [])
```

Root cause, confirmed in code:

- `state.initial_state` seeds two separate keys: `envelope` (the trigger payload) and an **empty** `artifacts`
  dict. The envelope is never decomposed into artifacts.
- `task_runner._gather_inputs` **hard-asserts** every declared input is already present in `state["artifacts"]`.
- Introspected capabilities declare a required per-tool input artifact (`<tool>_input`). Nothing seeds the entry
  task's input from the envelope, and each tool's **output** artifact (`<tool>_output`) has a *different name*
  from the next tool's **input** (`<tool>_input`), so nothing chains. The entry task fails before any tool call;
  even past it, mid-chain tasks would fail identically.

The seed pack (`wire-repair-standard`) runs only because it was hand-authored with two properties the introspected
model lacks: its entry `enrich_investigation` capability declares **`inputs: []`** (reads the envelope directly),
and every downstream capability reads a **shared** artifact an upstream task produced
(`dossier → beneficiary → repair → screening → resolution`).

There is also a **validator↔runtime disagreement**: pack validation downgrades an unproduced input to a soft
`unproduced_input` **warning** ("assumed seed state"), while the runtime provides no such seeding and hard-fails.
A "0 errors" pack therefore dies at step 1. Closing that disagreement is part of this decision.

## Decision

### D1 — Add an optional `input_map` to capability bindings

A capability binding MAY declare an `input_map`: for each declared input, a **source** the runtime resolves at
execution time. Sources (domain-neutral; no hardcoded envelope shape):

- **`{"from": "trigger"}`** — the process trigger payload (today `state["envelope"]`; post-ADR-047 the pack's
  declared trigger artifact), whole, or a dotpath: `{"from": "trigger", "path": "reason_codes"}`.
- **`{"from": "artifact", "name": "<upstream_output_name>"}`** — a named artifact an upstream binding produced,
  whole, or a dotpath: `{"from": "artifact", "name": "enrich_investigation_output", "path": "dossier"}`.
- **Composite** — when a tool input is an object of several fields, the value may be
  `{"fields": {"<field>": <source>, ...}}`, each field resolved independently. This is what builds an MCP tool's
  `arguments` from a mix of the trigger and upstream outputs (e.g. `assess` ← `{dossier: enrich output,
  exception_id: trigger.exception_id, reason_codes: trigger.reason_codes}`).

`input_map` is **optional and additive**. A binding without it keeps today's behaviour exactly.

### D2 — Runtime resolves inputs through the map, falling back to name lookup

`_gather_inputs` becomes: for each declared input `spec`,

1. if `input_map` has an entry for `spec.name` → resolve the value from the source(s) against
   `state["envelope"]` / `state["artifacts"]` (supporting whole, dotpath, and `fields`);
2. else → the current behaviour: `assert spec.name in artifacts; use artifacts[spec.name]`.

The resolved value is the capability's input (for `mcp`, it constructs the tool-call `arguments`). Seed packs —
which chain by shared names and have no `input_map` — hit branch (2) and are unaffected.

### D3 — Validator↔runtime seed-state contract (validate the real data-flow)

Pack validation stops *assuming* seed state and validates what the runtime will actually do:

- An input mapped `from: trigger` is satisfiable — validate its dotpath against the **trigger artifact schema**
  (once declared per ADR-047; until then, accept `trigger` as opaque).
- An input mapped `from: artifact` MUST reference an artifact **produced by an upstream binding** on every path
  that reaches this node; if not, it is an **error** (`binding_input_unproduced`), not a warning.
- An input with **no** map entry that is **not** produced upstream is an **error** (it will hard-fail at runtime),
  replacing today's soft `unproduced_input` warning. The only inputs that may be unproduced-and-unmapped are
  those the runtime genuinely seeds (none today — so this is an error until a seeding rule exists).

Net: a pack that would fail at runtime for a data-flow reason now **fails validation** with an element-named
error, at the step where it can be fixed.

### D4 — Authoring is data, at the Bindings step

The `input_map` is authored during onboarding (Bindings step) — it is process **data**, never platform code, and
it references the trigger and upstream outputs by name/path only (domain-neutral, consistent with ADR-047).
Inference SHOULD pre-suggest: the entry capability task → `from: trigger`; a task input whose schema matches a
single upstream output → that output. Suggestions are always operator-overridable.

## Consequences

- **Positive:** introspected MCP-per-process packs become executable — the entry task sources from the trigger,
  mid-chain tasks source from upstream outputs, all as authored data. The validator↔runtime gap closes: no more
  "activate-then-die-at-step-1." Seed packs are unchanged (no `input_map`).
- **Cost:** the operator authors a small mapping per capability task (mitigated by inference suggestions). The
  validator, runtime, manifest/contract, and the wizard Bindings step all change (additive).
- **Migration:** additive field; existing active packs keep working. The `ws-stan` MCP pack is re-onboarded (a new
  version) with `input_map` authored — the reference proof this ADR works end to end.

## Alternatives considered

- **Co-design the MCP tool schemas to chain via shared artifact names + a no-input entry tool** (mirror the seed).
  Rejected as the *general* mechanism: it forces every process's tools to agree on artifact names and abandons the
  per-tool-artifact introspection convention the MCP Guideline defines. Fine as an occasional modeling choice, not
  the platform contract.
- **Auto-seed only the entry task's input from the trigger.** Rejected as insufficient — it fixes step 1 but
  leaves every mid-chain input unwired.
- **Relax `_gather_inputs` to not assert.** Rejected — it turns a loud data-flow bug into silent empty inputs.

## Acceptance

1. A capability binding with `input_map` sourcing the entry input `from: trigger` and each later input `from:
   artifact` (an upstream output) executes end-to-end; `_gather_inputs` never asserts on a mapped input.
2. Validation errors (not warnings) on an unmapped-and-unproduced input, and on an `input_map` referencing an
   artifact no upstream binding produces — naming the element/field.
3. Seed packs (no `input_map`, shared-name chaining) validate and run exactly as before.
4. The re-onboarded `ws-stan` MCP pack runs an `AC01` exception through `Enrich → Assess → …` driving the MCP
   server, with the `input_map` authored as data and zero platform-code change per process.
