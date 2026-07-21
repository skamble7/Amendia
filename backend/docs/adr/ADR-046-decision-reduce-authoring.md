# ADR-046 — Decision / reduce capability authoring in the wizard

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-037 (native DMN `decision`), ADR-038 (`reduce`),
ADR-024 (self-descriptive inline runtime), ADR-044/045 (the wizard catch-up + persona UX). **Track:** Onboarding
Track 2 — the final wizard-catchup track. Adds a form-driven path to author the two **inline-configured**
capability kinds directly in the wizard, alongside MCP introspection.

## Context — authoring plumbing onto an existing target

The `decision` / `reduce` **contract, runtime, and validator already ship**: `DecisionRuntime{kind, table}` /
`ReduceRuntime{kind, config}` (`capability.py`), the shared evaluators + `validate_table` / `validate_reduce`
(`amendia_bpmn.dmn` / `.reduce`) producing `dmn_*` / `reduce_*` findings, and the 7-stage validator resolving a
`decision`/`reduce` capability like any kind. But capability **creation** in the wizard was MCP-only — a
native-DMN or reducer pack could be onboarded only by pre-seeding those capabilities. This task adds the
**authoring + staging surface**, mirroring the MCP path. No new execution/validation semantics.

## Decision

### 1 · Backend — stage a `decision` / `reduce` capability (mirror the MCP path)

`StagedCapability` gains a **`kind`** (`mcp` | `decision` | `reduce`) plus the inline payload (`table` /
`config`); `endpoint`/`tool` become optional (mcp only). `SetCapabilitiesRequest` gains `decision_specs[]` /
`reduce_specs[]`, staged in the **same** `set_capabilities` transition as the MCP tools (one invalidation
cascade). Each spec carries the inline `table`/`config`, an editable `cap.<domain>.<name>` id, the **input**
artifact key (an existing/staged upstream artifact the table's input expressions / the reduce source read), and
the **output** artifact identity. On stage:

- **Validate inline** with the shared checks — `validate_table(parse_decision_table(table))` /
  `validate_reduce(parse_reduce_config(config))` — surfacing `dmn_*` / `reduce_*` as field errors (fail the
  stage on error severity, like a non-compliant MCP tool). The validators are **reused, not re-implemented**.
- **Infer the output artifact.** A decision's **verdict** schema is built from the table `outputs` — each output
  column → a field, marked **required** (so a downstream gateway can branch); a string column with literal rule
  values becomes an **enum** of the distinct `then` values. A reduce's **summary** schema is the single
  `output_field`, typed by the op's result kind (quantifier→boolean, count→integer, numeric→number,
  positional→string). Both are normalized like an MCP output artifact (`normalize_artifact_schema`).

`_capability_descriptor` emits the runtime by kind — an inline `decision`/`reduce` (always `read_only`) or the
existing `mcp`. The assemble dry-run runs the **unchanged** 7-stage validator (which re-validates the
table/config + reconciles IO). A decision binds a `businessRuleTask`, a reduce a `serviceTask`, as an ordinary
capability executor — no binding-layer change.

### 2 · Frontend — two builder forms in the Capabilities step

A **DMN decision-table builder** (a grid: ordered input columns `expression`+`type`, ordered output columns
`name`+`type`, a hit policy, and rules whose input cells are bounded unary tests and output cells are values)
and a **reduce config builder** (source list artifact + `item_path` + op + optional predicate + `output_field`)
sit alongside MCP introspect + catalog reuse. Both emit the normalized `table` / `config`; validation is
authoritative on stage (the server's shared `dmn_*`/`reduce_*` findings surface inline per capability). The
Track-3 **"decision table candidate"** badge on a `businessRuleTask` becomes a one-click *author decision table*
action (pre-filling the builder's id) in the Capabilities step where the builder lives.

## Consequences

- An operator authors a `decision` (DMN table) or `reduce` (config) capability **in the wizard**, live-validated
  by the shared checks, staged with an inferred verdict/summary artifact, bound to a businessRuleTask / serviceTask,
  and activated — **no pre-seeding, no code**. The session model gains the decision/reduce staging shapes → the
  registry OpenAPI snapshot + `registry.ts` were regenerated (additive). MCP creation + catalog reuse are
  unchanged; standard/projection packs onboard byte-unchanged. **With Track 2 shipped, the wizard now authors
  everything the runtime executes** — the wizard catch-up (ADR-044/045/046) is complete.

## Non-goals

- No new capability kinds beyond `decision`/`reduce` (skill/llm/deep_agent stay reuse-only). No change to the
  DMN/reduce **evaluators or validators** (reused). No full FEEL beyond the bounded unary surface. No new steps
  (the builders live inside the Capabilities step). **No DMN-XML import** this cut (author the normalized table
  directly; `parse_decision_table` already accepts XML, so an import affordance is a later nicety).
