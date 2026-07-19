# ADR-037 — Native DMN decision tables (`decision` capability kind)

**Status:** Accepted · **Date:** 2026-07-17 · **Builds on:** ADR-033 (task kinds — `businessRuleTask`
routes to a bound capability, `decisionRef` captured advisory-only), ADR-024 (self-descriptive/pinnable
runtime), ADR-011/020 (capability execution core). **Backlog:** ships Deferred-Backlog item **#2** (native
DMN); defers a collection-reduction/summary capability as a new line.

## Context

A `businessRuleTask` today executes via a *hand-written bound capability*; `decisionRef` is captured for
inference only. We want business users to author payment rules as **auditable decision tables** — typed inputs
→ a verdict artifact through FEEL unary tests + hit policies — with no code. The value is authoring ergonomics;
a capability already covers execution, so this is additive and opt-in.

## Decision

**A DMN decision is a new capability *kind* (`decision`), not a new registry, evaluated by a scoped
build-not-adopt evaluator.**

- **`decision` capability kind (contract).** A `DecisionRuntime` carries the **decision table inline**
  (normalized JSON), pinned with the capability at activation like any other kind (self-descriptive, ADR-024).
  Typed `inputs`/`outputs` exactly like any capability (input artifact(s) → the verdict output artifact);
  `side_effect` is always `read_only`. A `businessRuleTask` binds a `decision` capability; the entire
  capability registration / pinning / resolution / IO-validation machinery is reused — **no separate DMN
  registry**. A `businessRuleTask` bound to a non-decision capability keeps today's behaviour (native DMN is
  opt-in).

- **Build, don't adopt (evaluator).** A scoped, auditable evaluator in the shared `amendia_bpmn.dmn` (imported
  by BOTH the registry validator and the runtime — one implementation, like the BPMN parser), same philosophy
  as `expr.py`: a **bounded FEEL unary-test surface** and NOTHING else. Per cell: literal equality
  (`"PADDED"`/`42`/`true`), comparisons (`< <= > >= =`), ranges (`[a..b] (a..b] [a..b) (a..b)`), enumerations
  (comma-separated), `not(…)`, and the dash `-` (always matches). A cell outside the surface is a
  **validation error** (`dmn_bad_unary_test`), never a silent pass. No FEEL functions/arithmetic/contexts/BKMs.
  Hit policies: `UNIQUE` (exactly one match, else runtime error), `FIRST`, `PRIORITY` (highest by the first
  output's `priority_order`), `ANY` (many may match but all must agree), `COLLECT` (all matches → a list; no
  aggregators — deferred). Evaluation is pure over `(table, inputs)` — deterministic, rule order = table order.

- **Runtime.** `execute_capability` gains `_execute_decision`: parse the inline table, `evaluate` over the
  bound inputs (dotpaths root on the binding input names), produce the verdict artifact — the host validates it
  against the pinned output schema exactly like any capability output. A `UNIQUE`/`ANY` conflict or no-match at
  runtime is a **technical** `CapabilityError` (a table that passed validation but misfires is a bug, not a
  modeled business outcome) — **never routed to an error boundary** (contrast ADR-030/035).

- **Validation (registry).** Stage 3 resolves a `decision` capability like any other. New error-severity
  checks off the shared evaluator: `dmn_table_malformed`, `dmn_unknown_hit_policy`, `dmn_bad_unary_test`,
  `dmn_input_unresolved` (an input-expression dotpath whose root is not a declared binding input — mirroring
  the gateway-variable "must be produced" rule), `dmn_output_unmapped` (an output column absent from the pinned
  verdict artifact schema), and `dmn_rules_overlap` (a *statically detectable* UNIQUE/ANY overlap; best-effort,
  no false positives — the runtime still guards). An advisory `decisionRef` naming a different table id is a
  `decision_ref_mismatch` warning.

- **Seed.** A sample `wire-repair-dmn` pack ships a `businessRuleTask` bound to a `decision` capability (dossier
  gpi-status + amount → repair verdict), exercised end-to-end like `wire-repair-standard`.

## Consequences

- Business rules become auditable tables, pinned and validated like any capability, feeding downstream gateways
  unchanged — no code, no new registry, no widening of `expr.py`. Registry and runtime share one evaluator, so
  a table that activates always runs.

## Deferred / non-goals

- **DMN authoring wizard UI** — the runtime/contract/validation/seed land here; a form-based table authoring
  surface in the onboarding wizard is a follow-on.
- **COLLECT aggregators** (sum/min/max/count) — first cut is list-only.
- **Full FEEL** (functions, arithmetic, contexts, BKMs) — deliberately out of the bounded surface.
- **Collection-reduction / summary capability** — the "any/all over a list" gap noted when multi-instance
  shipped (ADR-036): `expr.py` can't quantify over a list, and the intended answer is a small *reduce*
  capability (list → a scalar/summary artifact a gateway can branch on), not a wider expression language. Newly
  deferred (backlog).
