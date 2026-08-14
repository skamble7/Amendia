# Claude Code prompt — harden gateway conditions: **normalize Camunda-authored BPMN at upload + guided design-time validation** (one shared grammar)

Production hardening for the gateway-condition class of failure. A team onboarded a pack whose gateway `G11`
carried `limit_breached = true`; it passed onboarding and only blew up at **runtime compile**
(`ConditionSyntaxError` → `CompilerError`), which also 500s every `GET /instances/{id}/state` (compile runs on
spawn AND on state reads). Root causes, both to be closed here:

1. **Two different notions of "valid condition."** The runtime grammar (`agent-runtime/app/engine/expr.py`,
   `_COND`) is the only real arbiter, but design time never runs it — `pack_validator` stage 6 only checks the
   condition's LHS first-segment resolves to a produced output. So `limit_breached = true` (unquoted boolean, no
   field path) sailed to `active`.
2. **Authoring-format mismatch.** Amendia's exporter writes **raw FEEL** (`decision.rbo_decision = "approve"`
   with `language=".../FEEL/"`). Generic/Camunda modelers write **`${…}`-wrapped** conditions
   (`${decision == "Proceed"}`, no FEEL `language` attr). Amendia does **not** strip `${…}`, and the onboarding
   variable-inference regex (`inference._condition_variable`, `^\s*([A-Za-z_]…)`) can't even match a `${` — so a
   Camunda-authored condition **silently** infers no gateway variable (empty Source artifact) at design time and
   fails at runtime.

**The fix (Sandeep's design):** at BPMN upload, **auto-normalize what is provably lossless** and **notify the
user** what changed; for the residue that needs author intent, **block with a guided, schema-enriched fix** — not
a cryptic 422. And make the runtime grammar the **single shared source of truth** so the two services can never
drift again. This is what turns an error-prone manual XML fix into a confirm-a-suggestion step.

Backend is the substance (shared grammar + normalizer + guided validation + structured onboarding response); a
**bounded** webui deliverable surfaces the notice. Can land as two commits (backend, then webui) if you prefer.

## Read first

- `backend/services/agent-runtime/app/engine/expr.py` — the runtime grammar SoR: `_COND` (=
  `^\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*(==|=|!=)\s*"([^"]*)"\s*$`), `parse_condition`,
  `evaluate` (string compare). This regex is the arbiter; everything below must agree with it byte-for-byte.
- `libs/amendia_bpmn/amendia_bpmn/{parser.py,semantics.py,model.py}` — where a `conditionExpression`'s text is
  read verbatim (`parser.py` ~L248–255 → `Flow(condition_expr=...)`; `semantics.py` ~L193–196 → the raw
  `condition`). This is the extraction seam the normalizer plugs into. Confirm which shared libs `agent-runtime`'s
  engine already imports — the shared grammar module must be reachable from **both** agent-runtime and
  process-registry (if `amendia_bpmn` isn't a dep of the runtime engine, use whichever common lib is:
  `amendia_common`/`amendia_contracts`). One home, both import.
- `backend/services/process-registry/app/services/onboarding.py` — `attach_bpmn` (~L533) → `extract_semantics`
  (~L548); `_parse_and_check_bpmn` (~L1245); and the **precedent** `normalize_artifact_schema` (already run in
  onboarding, ~L85/1515/1547) — mirror its "normalize + carry the changes" style.
- `backend/services/process-registry/app/services/inference.py` — `_condition_variable`, `_CONDITION_LHS`, the
  gateway-variables loop (~L200–213). Once conditions are normalized upstream, this starts inferring variables
  for Camunda-authored flows too (the silent-miss goes away) — verify that.
- `backend/services/process-registry/app/validation/pack_validator.py` — stage 6 gateway checks (`_COND_LHS`, the
  `gvars` loop ~L726–790), `_latest_active_schema`, `_required_path_ok`. The blocking guard + the schema lookups
  the guided suggestion reuses live here.
- `backend/services/process-registry/app/services/copilot/reconcile.py` — `source_artifact` resolution (~L277)
  and `_output_artifact_map` (~L331): how a gateway's LHS first-segment resolves to the bound output artifact.
  The guided suggestion reads that artifact's schema.
- `backend/services/process-registry/app/models/onboarding.py` — `StagedGatewayVariable`, the finding/proposal
  models, the onboarding-session shape. Add the normalization/issue carriers here.

## Deliverables

### 1. One shared condition grammar (kill the drift)
Extract the canonical grammar into a shared module both services import (pure, no I/O):
- `CONDITION_RE` — the exact `_COND` pattern, moved here (single definition).
- `parse_condition(expr) -> (lhs, op, rhs)` — moved from `expr.py`; **`agent-runtime` delegates to it** so runtime
  behavior is byte-identical (its tests must stay green unchanged). `evaluate` stays in agent-runtime.
- `normalize_condition(raw) -> (canonical, changes: list[str])` — the Tier-1 lossless transforms (see #2).
  Idempotent; a no-op (returns `(raw, [])`) on already-canonical input.
- `classify_condition_error(canonical) -> reason` — for a non-canonical residue, a machine reason
  (`missing_field` | `unquoted_rhs` | `unsupported_operator` | `wrapper_unresolved` | `not_parseable`) used to
  build guided messages.

### 2. Tier-1 normalizer — lossless, at the extraction seam (do NOT rewrite the uploaded XML)
`normalize_condition` applies only **provably truth-preserving** transforms:
- strip a **balanced outer** `${ … }` / `#{ … }` wrapper (only when the whole trimmed body is wrapped);
- convert **outermost** single-quoted string literals to double-quoted (`'approve'` → `"approve"`);
- canonicalize whitespace (and, if you canonicalize the operator, pick one — but note the runtime already accepts
  both `==` and `=`, so this is cosmetic).

Rules: if a transform is **ambiguous or not clearly lossless** (e.g. a literal containing a `"`, nested/unbalanced
braces, anything that could change the truth value), **do not transform — leave it for validation to flag.**
Better to flag than mis-rewrite. Apply normalization **before** `extract_semantics`/inference in `attach_bpmn`, and
carry both forms on the flow model (`condition_raw` + canonical `condition`) rather than mutating the stored BPMN —
the uploaded file stays an immutable record; the canonical form is derived deterministically everywhere
(inference, validator, runtime). Record a per-flow changelog `{gateway_id, flow_id, from, to, changes[]}`.

### 3. Tier-2 guided validation — blocking, schema-enriched (in `pack_validator` stage 6)
After normalization, run `parse_condition` on every conditional flow's canonical condition. On failure, emit a
**blocking** stage-6 error (pack cannot go `active`) — but make it *guided*, not cryptic. Using the gateway's
already-resolved `source_artifact` + `_latest_active_schema`, enrich the message with the concrete fix:
- **`missing_field`** (`decision` / `limit_breached` with no dot): list the artifact's **required string fields**
  and suggest `"<obj>.<field> = \"<value>\""`.
- **`unquoted_rhs`** (`= true`, `= 5`, bare ident): "RHS must be a double-quoted string"; if the field is an
  enum, list its allowed values and suggest one.
- **`unsupported_operator`** (`>`, `and`, `contains(...)`): "only `= / == / !=` string comparison is supported —
  compute this upstream and branch on a categorical string output."

Include the machine `reason` + a structured `suggestion` (obj, candidate fields, enum values, a ready condition
string) on the finding, so the UI can render a one-click-ish fix. **Never auto-apply a Tier-2 fix** — choosing
which value means "take this branch" is author intent (guessing gives silent wrong-routing, worse than an error).

### 4. Structured onboarding response
Surface, on the `attach_bpmn` result and the validation report, two lists:
- `condition_normalizations[]` — informational (what was auto-converted, before/after) for the upload notice.
- `condition_issues[]` — the guided Tier-2 findings (gateway_id, raw, canonical, reason, suggestion). Blocking.

Wire these onto the onboarding-session / validation models (mirror `normalize_artifact_schema`'s warning-carrying
style). Also confirm the win: a Camunda-authored `${decision == "Proceed"}` now **normalizes → infers its gateway
variable → resolves its Source artifact** instead of silently blanking (assert in a test).

### 5. webui — the upload notice + guided fix (bounded)
- **Upload / Understanding step:** an informational banner when `condition_normalizations` is non-empty — "Converted
  N condition(s) from Camunda `${…}` syntax to Amendia FEEL", expandable to per-flow before/after. Non-blocking.
- **Gateways step:** for each `condition_issues` entry, show the guided message + suggested condition inline near
  that gateway's (already-editable) dot-path / Source-artifact fields; the author applies the suggestion or edits.
  Keep it owner-gated like the rest of the step. A pack with unresolved issues can't reach "Review & go live".
- No new SSE, no new endpoints — this rides the existing attach/validation responses.

## Do not
- Do not let the design-time grammar diverge from the runtime — it must be the **same module** the runtime uses
  (agent-runtime delegates; don't copy-paste the regex). This drift is the bug.
- Do not auto-apply any transform that could change which branch fires. Tier-1 is lossless syntax only; everything
  value/field/logic-shaped is Tier-2 (flagged, author-confirmed).
- Do not rewrite/mutate the uploaded BPMN XML; derive the canonical form. Keep the original for audit/diff.
- Do not change `evaluate` or the runtime's accepted grammar (still `= / == / !=`, string compare, quoted literal).
  Do not weaken owner-gating or add endpoints/SSE.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance
- **Golden untouched:** `decision.rbo_decision = "approve"` normalizes to itself (no changes), parses, passes —
  zero behavior change for existing valid packs; agent-runtime's `expr` tests pass unchanged after delegation.
- **Camunda unwrap:** `${decision == "Proceed"}` → canonical `decision == "Proceed"`, listed in
  `condition_normalizations`; its gateway variable now infers and Source artifact resolves; and because it's still
  field-less it ALSO raises a Tier-2 `missing_field` issue suggesting `decision.rbo_decision = "…"` from the
  bound `capture_decision_output` schema.
- **The production case:** `limit_breached = true` → Tier-2 blocking `unquoted_rhs` (+ `missing_field`), guided
  suggestion `limit_breached.decision = "<enum>"` drawn from `update_case_exposure_review_output`'s required
  string fields; pack **cannot** go active until fixed.
- Single-quote → double-quote normalization works; an ambiguous case (literal containing `"`, unbalanced braces)
  is **left untouched and flagged**, not mis-rewritten.
- `pytest` green across the shared grammar lib, agent-runtime (unchanged behavior), process-registry (new
  normalization + guided-validation cases incl. the three above), and the webui `vitest` for the banner/issue
  rendering; `tsc`/build clean; OpenAPI snapshot re-dumped + `gen` regenerated for the new response fields.
- **Reviewer note:** live after `docker compose build agent-runtime process-registry` (+ webui rebuild).

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_condition_normalization_guard_report.md` (uncommitted):
(1) outcome one-liner; (2) where the shared grammar landed + how agent-runtime delegates (proof runtime behavior
is unchanged); (3) the Tier-1 transforms + the "ambiguous → don't touch" rule + where normalization hooks (before
extract_semantics) and how raw+canonical are carried without mutating the upload; (4) the Tier-2 guided validation
(reasons, schema enrichment, blocking) + the three acceptance conditions' actual messages; (5) the structured
onboarding response fields + the webui banner/issue surface; (6) verification — exact commands + results; (7)
follow-ups (e.g. the tool-I/O visualization on the Artifacts step — tracked separately). One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. One shared grammar (no drift), lossless auto-normalize +
notify, guided-and-blocking for the residue, never guess a branch value, don't mutate the upload. Reuse
`normalize_artifact_schema`'s style, the stage-6 schema lookups, and the existing editable Gateways fields.
