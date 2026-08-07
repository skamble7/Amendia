# Claude Code prompt — onboarding-time type-compatibility guard for capability input mappings

You are adding a **design-time guard** to the Amendia onboarding path so that a type-incompatible input mapping
(the kind that just caused the wire "Screen" silent-hold) is caught in the wizard/at commit, instead of failing
at runtime. This is the durable follow-up to the wire-screen debug (see
`backend/docs/_build-reports/claude_code_prompt_wire_screen_onboarding_regression_report.md`) — the runtime
masking bug is already fixed in `agent-runtime/app/engine/compiler.py`; do **not** touch that.

## Background (established, don't re-litigate)

The copilot derived `Screen.party ← trigger.payment.creditor`, but the tool's `screen_party` input declares
`party.account` as a **string** while the trigger's `payment.creditor.account` is an **object** `{id, scheme}`.
The real MCP server type-checks its closed `inputSchema` and rejects the call (`isError`, no `error_code`) →
runtime fallback `MCP_TOOL_ERROR` → (previously) a catch-all boundary masked it as a compliance hold. The same
class of bug exists at `Notify.recipients ← related_messages` (array-of-objects → array-of-strings). These are
**type mismatches between the mapped source's JSON type and the consuming tool field's declared type** — knowable
at onboarding, before any run.

## Goal

At onboarding, when a binding's `input_map` maps a source (trigger dotpath, or an upstream artifact dotpath) into
a capability/tool input field, compare the **source's JSON type** (from the pack's declared trigger schema or the
upstream artifact schema) against the **tool field's declared type** (from the capability `inputSchema`). Flag a
definite incompatibility so the operator sees and fixes it in the wizard, and reject it at commit — never let a
guaranteed-to-fail mapping reach an active pack.

## Read first

- `process-registry/app/services/copilot/reconcile.py` — `_capability_input_sources` (the derivation the report
  named) and how it resolves each input field to a source + the schemas it already has in hand.
- `process-registry/app/services/copilot/service.py`, `mutations.py` — how findings/warnings are surfaced to the
  wizard (mirror the ADR-057 opaque-object warning path).
- `process-registry/app/services/onboarding.py` and the `PackValidator` (wherever bindings/input_map are
  validated at assemble/commit) — where a hard reject belongs.
- `libs/amendia_contracts/amendia_contracts/process_pack.py` — `InputSource` (`TriggerSource` / `ArtifactSource`
  / `FieldsSource`) and `Binding.input_map`; the trigger schema lives on the pack (`ProcessPackManifest.trigger`,
  ADR-047 D1/ADR-049), artifact schemas in the registry.
- How a JSON-Schema is flattened to `{dotpath: json_type}` already exists — reuse it (`flatten_schema_fields` /
  `infer_field_types`, per ADR-049); do not reinvent.
- The concrete cases: `mcp_stub/servers/wire_transfer_exception/.../schemas.py` (`SCREEN_INPUT` party.account
  `_STR`, `NOTIFY_INPUT` recipients) and the trigger schema `art.wire_stan.wire_exception_received`.

## Tasks

1. **Type-compatibility check (domain-neutral core).** Add a helper that, given a source JSON type at a dotpath
   and the target tool-field JSON type, returns compatible / incompatible / unknown. Rules:
   - Compatible: exact type match; `integer`→`number`; anything → a genuinely permissive target
     (`additionalProperties:true` / no declared type / open object); a value → an `enum` it's valid for.
   - **Incompatible (flag):** `object`→`string`, `array`→`string`, `array`-of-`object` → `array`-of-`string`
     (and analogous scalar-vs-container mismatches), i.e. the source can never satisfy the target's declared type.
   - **Unknown (skip, don't flag):** either side's schema is absent/opaque — degrade gracefully exactly as
     ADR-057 does; never block on missing information.
   Handle nested objects field-by-field and array `items` element types. Be careful with `_typed_open`-style
   targets: additionalProperties may be open while a **declared** property (like `account: string`) still binds —
   a declared-property mismatch is still incompatible.

2. **Surface at derivation (soft).** In `_capability_input_sources`, attach a warning-level finding for each
   incompatible mapping — same channel/shape as the ADR-057 opaque-object warning — naming the binding element,
   the input field, the source dotpath, and the two types ("`Screen.party.account`: source `object` cannot
   satisfy tool field `string`"). The copilot should prefer a type-compatible source when one exists.

3. **Enforce at commit (hard).** In the assemble/commit validator, a **definite** incompatibility (not unknown)
   is a hard reject with the same message — a pack that will always fail this call must not go active.

4. **Make the wire happy path reachable (reference fix — allowed here, it's the fix not a paper-over).**
   Decide and implement the minimal correct change so a *correct* onboarding of `wire-stan` can screen the real
   creditor: either (a) relax the stub `SCREEN_INPUT.party.account` (and `NOTIFY_INPUT.recipients`) to accept the
   real trigger shapes (`account` is genuinely `{id, scheme}`; recipients genuinely structured), or (b) constrain
   the mapping to a compatible leaf. Recommend which in the report; prefer the one that keeps the screen
   semantically correct (it needs the party identity). Note this edits reference-domain data deliberately.

5. **Tests.** Unit tests for the type-compat helper (each compatible/incompatible/unknown case), a derivation
   test that the `party.account` object→string mapping produces the warning, and a commit test that it is
   rejected. If the copilot LLM is reachable in this run, re-onboard `wire-stan` and drive an `unable_to_apply`
   trigger to `End_Resolved` with `ApplyRepair` and `Notify` each firing their `approve_actions` gate and
   executing only after approval; if the LLM is not reachable headless, document the exact manual re-onboard +
   drive steps for the operator instead of faking it.

## Do not

- Do not touch the ADR-059 vocabulary or the `compiler.py` masking fix (already correct).
- Do not weaken HITL gating.
- Do not make the guard domain-aware — it compares JSON types only, no business nouns.
- No git write ops. Leave the tree dirty; the operator owns commits.

## Acceptance

- The type-compat helper is domain-neutral, unit-tested across compatible/incompatible/unknown, and degrades to
  "skip" on missing schemas (never a false block).
- Onboarding `wire-stan` surfaces the `Screen.party.account` (and `Notify.recipients`) incompatibility as a
  wizard warning; committing such a pack is hard-rejected.
- With the reference fix from Task 4, a correctly-onboarded `wire-stan` reaches `End_Resolved` (documented if the
  e2e re-onboard needs the LLM).
- `stan-dine` onboarding/e2e still green; backend `pytest` green for `process-registry` and `agent-runtime`.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_onboarding_type_compat_guard_report.md` (uncommitted):
(1) outcome one-liner; (2) the type-compat rules implemented + where the guard hooks in (derivation + commit);
(3) the Task-4 reference decision and why; (4) whether the wire happy path was driven to `End_Resolved` here or
left as documented manual steps, and why; (5) verification — exact commands and results (`pytest`, any e2e);
(6) anything left open for the reviewer. Keep it to a screen or two.

## Working agreement

No git writes — leave the tree dirty for Sandeep to review and commit. Prefer the fix at the right layer over a
shim. Stay inside the Amendia repo and the scope above.
