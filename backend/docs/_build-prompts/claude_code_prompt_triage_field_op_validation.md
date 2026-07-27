# Claude Code Prompt — Triage `field`/`op` validation against the trigger schema (batch-4)

A triage rule referencing a field that isn't on the envelope (`reason_code` vs the real `reason_codes`) or a
type-incompatible operator (`eq` on a list) **validates clean and silently never triages** — the exception lands
"No process." We already hit both. `check_predicate` only checks structure (op ∈ the allowed set, field is a
non-empty string); it never checks the field against the actual payload or the op against the field's type. Add
that check at authoring time so this class becomes an element-named error at the Triage step, not a silent
runtime miss. Domain-neutral (ADR-047): validate against the pack's **declared trigger schema**, never hardcoded
field names.

## Dependency / sequencing

The strong form needs a **trigger schema** to validate `field` existence and type against — i.e. the pack's
declared trigger artifact (ADR-047 D1). Sequence this **with or after** ADR-047 D1; in fact this bug is a concrete
motivator for it. Where a trigger schema is available (the pack's registered trigger artifact, or a
deployment-provided sample-envelope schema), do the full check; where none is declared, degrade gracefully to the
op-type/structural checks below — **do not** hardcode `reason_codes` or any envelope shape.

## Recon

- `backend/services/process-registry/app/validation/predicates.py` — `_LEAF_OPS`, `_resolve_path`, `evaluate`,
  and `check_predicate` (structural only). Add schema-aware validation here (pure, reused by set_triage + dry-run).
- `app/services/onboarding.py::set_triage` — call the new check with the pack's trigger schema.
- `app/validation/pack_validator.py` — the stage-7 triage smoke (currently info) — elevate real authoring errors.
- `webui/src/features/registry/OnboardingWizard.tsx::TriageStep` — offer schema fields + type-appropriate ops.

## Change 1 · Schema-aware predicate validation (backend, pure)

Add `validate_predicate(predicate, trigger_schema) -> list[Finding]` (or extend `check_predicate` with an optional
schema). Walking the `all`/`any`/`not`/leaf tree:

- **Field existence** — each leaf `field` dotpath must resolve to a property in `trigger_schema`. If not →
  `triage_field_unknown` error, naming the field and a **nearest-match suggestion** (edit-distance against the
  schema's property names, e.g. `reason_code` → "did you mean `reason_codes`?").
- **Op ↔ type compatibility** — from the field's JSON-schema type:
  - array field → allow `intersects`, `in`, `exists`; a scalar op like `eq`/`gt` on an array →
    `triage_op_type_mismatch` ("eq on array field 'reason_codes'; use intersects").
  - scalar (string/number/bool) → allow `eq`/`ne`/`in`/`starts_with`/`gt`/`gte`/`lt`/`lte`/`exists` per type
    (ordered ops only on number/date; `starts_with` only on string).
- Keep the existing structural checks. These run at `set_triage` (blocking 422, element/field-named) and in the
  dry-run.

## Change 2 · Elevate the dry-run signal

In stage-7, keep the `triage_rule_smoke` "matches N samples" as info, but a rule with a `triage_field_unknown` or
`triage_op_type_mismatch` is an **error**, not a silent pass. (A rule that is schema-valid but matches zero sample
envelopes may stay a warning — it's suspicious but not necessarily wrong.)

## Change 3 · Wizard — author against the schema

In `TriageStep`, when a trigger schema is known, render the leaf **field** as a picker of the schema's property
paths and the **op** as only the type-compatible operators for the chosen field; pre-suggest a sensible default
(e.g. an array field → `intersects`). The operator can't author `reason_code`/`eq`-on-array by hand. Where no
schema is available, fall back to free-text with the structural checks only.

## Non-goals

- No hardcoded envelope/field knowledge; everything derives from the declared trigger schema. No change to the
  predicate evaluator's runtime semantics, only added authoring-time validation. No new ops.

## Definition of done

- With a trigger schema present: a rule referencing an unknown field, or an op incompatible with the field's type,
  **fails `set_triage`/dry-run** with an element-named error + a nearest-match suggestion; the `reason_codes` +
  `intersects` rule validates; the Triage step offers schema fields + valid ops.
- With no trigger schema declared: structural checks unchanged, no false errors, nothing hardcoded.
- Tests: `triage_field_unknown` (+ suggestion), `triage_op_type_mismatch` (`eq` on array), a valid
  `reason_codes/intersects` rule passing, and the no-schema graceful path. `registry` + `webui` green.

## Batch-4 sibling

Third of the authoring-time-guardrails trio (with capability pre-select recall — done — and the capability-id
collision guardrail). Best sequenced with ADR-047 D1 (the trigger artifact), which is what gives it a schema to
validate against.
