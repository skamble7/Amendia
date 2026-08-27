# Gateway-condition hardening — shared grammar + normalize-at-upload + guided validation: report

## 1. Outcome

The gateway-condition failure class is closed at design time. There is now **one** condition grammar both
services import (no more drift); Camunda-authored `${…}` conditions are **auto-normalized (lossless) at upload
with a notice**; and any residue that needs author intent is a **blocking, guided, schema-enriched finding**
instead of a runtime `CompilerError` that also 500'd `GET /instances/{id}/state`. The production case
(`limit_breached = true`) can no longer reach `active`. All suites green (bpmn **194**, agent-runtime **393**,
process-registry **405**, webui **204** + build); the runtime grammar is byte-identical (compiler tests pass).

## 2. One shared grammar (kills the drift)

`libs/amendia_bpmn/amendia_bpmn/conditions.py` is the single source of truth (pure, no I/O):
`CONDITION_RE` (the exact historical `_COND`), `parse_condition` (returns `(segments, op, literal)` unchanged),
`normalize_condition`, `classify_condition_error`, `condition_lhs`. Both services depend on `amendia_bpmn`, so it
is the natural home. **agent-runtime delegates**: `app/engine/expr.py` now imports `CONDITION_RE`/`parse_condition`/
`ConditionSyntaxError` from the shared module and keeps only `resolve_path`/`evaluate` — no local regex copy.
Proof of no behavior change: `parse_condition` is moved verbatim (same return shape) and `tests/test_compiler.py`
(10) + the whole agent-runtime suite (393) pass unchanged.

## 3. Tier-1 normalizer — lossless, at the extraction seam (no XML mutation)

`normalize_condition(raw) -> (canonical, changes)` applies only provably truth-preserving transforms: strip a
**balanced outer** `${…}`/`#{…}` wrapper (whole-body-wrapped only — a brace-depth scan; `${a} and ${b}` is left
alone), and convert an **outermost** single-quoted literal to double-quoted (only when exactly two single quotes
and no `"` present). **Ambiguous → don't touch**: a literal containing `"`, unbalanced/multiple wrappers, or
multiple quoted parts are returned unchanged for validation to flag (better to flag than mis-rewrite a branch).
Idempotent. It hooks at the **extraction seam** — `parser.py` (`Flow.condition_canonical` + `condition_changes`)
and `semantics.py` (`SemSequenceFlow.condition` = canonical, `condition_raw` = verbatim, `condition_changes`) —
so the uploaded XML is **never mutated** (the raw text stays on `condition_expr`/`condition_raw` for audit) and
the canonical form is derived deterministically everywhere: the runtime compiler now evaluates
`condition_canonical or condition_expr` (lossless ⇒ byte-identical for valid packs), inference reads the
canonical `condition`, and the validator validates it.

**Inference win (confirmed by test):** because `SemSequenceFlow.condition` is canonical, a Camunda-authored
`${beneficiary == "repairable"}` now infers its gateway variable (`beneficiary`) and resolves its Source
artifact instead of silently blanking (the old `^\s*([A-Za-z_]…)` couldn't match a `${`).

## 4. Tier-2 guided validation — blocking, schema-enriched (`pack_validator` stage 6)

`_stage6_condition_grammar` runs the shared `parse_condition` on every conditional flow's canonical condition.
On failure it emits a **blocking** `gateway_condition_grammar` error carrying a machine `reason`
(`classify_condition_error`) + a structured `suggestion` (`obj`, `candidate_fields`, `enum_values`, a ready
`condition` string), enriched from the gateway's resolved `source_artifact`/produced-output schema
(`_required_string_fields`). A **field-less LHS** (parses but names the whole output object → can never branch)
is flagged as `missing_field` in addition to any parse reason. **Never auto-applied.** The three acceptance
messages (against the wire-repair seed, output `art.payment.assess_beneficiary_output` with required strings
`repair_verdict`[enum] + `rationale`):
- `${beneficiary == "repairable"}` → normalized + inferred, **and** a `missing_field` issue suggesting
  `beneficiary.repair_verdict = "repairable"`.
- `limit_breached = true` → **`unquoted_rhs`** ("the right-hand side must be a double-quoted string") **+
  `missing_field`**, suggestion drawn from the bound output's required string fields; `report.has_errors` → the
  pack **cannot** go active.
- `… > "…"` → `unsupported_operator` ("only `= / == / !=` string comparison is supported — compute upstream and
  branch on a categorical string output"), blocking.

## 5. Structured onboarding response + webui surface

- `BpmnInventory.condition_normalizations[]` (`ConditionNormalization`: gateway_id, flow_id, from, to, changes)
  — populated in `attach_bpmn`, informational. `ValidationReport.condition_issues[]` — the guided Tier-2
  findings (reason + suggestion), populated in `finalize()`. `Finding` gained `reason` + `suggestion`. OpenAPI
  snapshot re-dumped; `webui gen/registry.ts` regenerated (offline snapshot); the hand-kept `ValidationReport`/
  `ValidationFinding` types gained `condition_issues`/`reason`/`suggestion` + a `ConditionSuggestion`.
- **webui (`OnboardingWizard.tsx`):** `ConditionNormalizationNotice` — a non-blocking banner on the attach card
  ("Converted N condition(s) from Camunda `${…}` syntax…", expandable per-flow before/after). `GatewayConditionIssues`
  — per-gateway guided message + suggested condition inline in the (owner-gated) Gateways step, with an **Apply**
  that pre-fills the editable variable (only for a concrete suggestion — a `<placeholder>` offers no Apply, since
  choosing the value is author intent). A pack with unresolved issues can't reach go-live (blocking findings).

## 6. Verification

- `libs/amendia_bpmn`: `python -m pytest` → **194 passed** (incl. `tests/test_conditions.py`: parse, lossless
  normalize, idempotency, ambiguous-left-untouched, classify).
- `agent-runtime`: `uv run --extra dev pytest` → **393 passed, 4 skipped** (compiler byte-identical; the one
  white-box compiler test that mutated `condition_expr` now also sets `condition_canonical` — the field the
  compiler reads).
- `process-registry`: `uv run --extra dev pytest` → **405 passed** incl. `tests/test_condition_hardening.py`
  (golden untouched, Camunda unwrap + inference + missing_field, unquoted-rhs blocking, unsupported-operator
  blocking, single→double-quote normalized-then-passes) and the re-dumped **`test_openapi_snapshot`**.
  (`python scripts/dump_openapi.py`.)
- `webui`: `npx tsc --noEmit` clean; `npm run build` exit 0; `npx vitest run` → **204 passed** incl.
  `conditionHardening.test.tsx` (banner before/after, guided issue + Apply, no-Apply for placeholder). (A
  pre-existing jsdom `scrollIntoView` unhandled-warning in the attach test is unrelated to this change.)

## 7. Follow-ups

- **Attach-time issue preview:** `condition_issues` are computed at dry-run/go-live (they need bindings for the
  schema lookup); a coarse attach-time "this condition won't parse" hint (no schema enrichment) could surface
  even earlier. Not needed for the fix.
- **Tool-I/O visualization on the Artifacts step** (a richer per-binding input/output schema view) — tracked
  separately.
- **Reviewer note:** live after `docker compose build agent-runtime process-registry` (+ webui rebuild).
