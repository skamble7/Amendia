# Onboarding-time type-compatibility guard — implementation report

## 1. Outcome

**Done.** A domain-neutral JSON-Schema type-compatibility guard now catches the wire "Screen"/"Notify" class of
mapping bug at design time — surfaced as a wizard **warning at derivation** and a **hard reject at commit** — so
a guaranteed-to-fail mapping can't reach an active pack. The reference fix (relaxing the over-strict tool
contract) makes a correct `wire-stan` reach **`End_Resolved`** end-to-end on the live stack. All new logic is
unit-tested; `process-registry` and `agent-runtime` suites are green.

## 2. Type-compat rules + where the guard hooks in

Core (domain-neutral, JSON types only): `app/validation/type_compat.py` —
- `schema_type_compat(source, target) → "compatible" | "incompatible" | "unknown"`. **Incompatible** =
  structural mismatch a value can never satisfy: `object`/`array` → scalar, scalar/array → `object`,
  scalar/object → `array`, and recursively an `array<object>` → `array<string>` or a declared object
  **property** clash (the `_typed_open` `party.account: string` case). **Compatible** = exact match,
  `integer`→`number`, anything → a permissive target (no type / open object / `additionalProperties:true`),
  scalar↔scalar (coercible — never flagged, avoids false blocks). **Unknown** = either side opaque/absent, or an
  ambiguous union → **never blocks** (degrades exactly like ADR-057). Recurses declared object properties and
  array `items`. Companions: `schema_at_path` (navigate a source dotpath, unwrapping nullable unions) and
  `describe_mismatch` (names the offending leaf + the two types for the message). Reuses the ADR-049 type
  vocabulary (`integer`→`number`, nullable unions, enums).
- **Soft, at derivation** — `copilot/reconcile.py::_capability_input_sources`: for each trigger-sourced field
  whose declared name passed the over-map guard, compare the source dotpath's type (from the pack's trigger
  schema) to the tool field's declared type; on `incompatible`, raise a `CopilotOpenQuestion` (topic
  `input_map`) + a `_det` provenance line, naming element, field, source dotpath, and the mismatch (e.g.
  `'account': object cannot satisfy string`). The mapping is still emitted so the operator sees it in the
  wizard. Artifact-sourced fields / missing schema → skipped (unknown).
- **Hard, at commit** — `validation/pack_validator.py::_stage5_artifacts_io` (beside the existing
  `input_map_overflows_tool_schema` name guard): for each MCP binding's composite `{fields:{…}}`, resolve each
  field's source (trigger dotpath, or an upstream artifact dotpath via the produced-output schema) and target
  (the input artifact schema, which mirrors the tool `inputSchema` by ADR-025) and emit a hard
  `input_map_type_incompatible` error on a definite mismatch. Whole-source/scalar-path names remain governed by
  the existing overflow guard.

## 3. Task-4 reference decision + why

**Relaxed the stub tool contract (option a) for both fields** — `SCREEN_INPUT.party.account`
(`string` → typed-open `{id, scheme}`) and `NOTIFY_INPUT.recipients` (`array<string>` → `array<object>`) in
`mcp_stub/…/wire_transfer_exception/…/schemas.py`. Rationale: the screen genuinely needs the party identity, and
a wire creditor `account` **is** structured `{id, scheme}` (and `related_messages` recipients are structured) —
the tool's scalar declarations were simply wrong, so a semantically-correct `party ← payment.creditor` mapping
was failing a bad contract. The guard's role is to **surface** the incompatibility; the correct resolution when
you own the tool is to fix the over-strict contract (option b — constraining the mapping — is the right move
when the source really is the wrong thing; noted for operators who don't own the tool). Compliance self-check
still OK; the handler doesn't read these fields, so screening/notification behaviour is unchanged.

## 4. Was the wire happy path driven to End_Resolved here?

**Yes, live.** Rebuilt only the wire MCP-stub container with the relaxed schema (no re-onboard / LLM needed — the
reference fix makes the EXISTING `wire-stan` mappings type-compatible), fired an `unable_to_apply` trigger, and
instance `pi-b29c877436474015` ran: `Screen` **produced** `screen_party_output` (clears — no hold), `ApplyRepair`
and `Notify` each raised their `approve_actions` gate and executed the MCP tool **only after approval**, and the
instance **`completed outcome=End_Resolved`** (artifacts incl. `screening`, `notification_result`,
`repair_result`). Note: the guard code itself runs in tests, not in the live registry container (my
process-registry changes are uncommitted, so not in the running image) — the live run validates the reference
fix; the guard is validated by the unit/commit tests below. To activate the guard live, the operator rebuilds
`process-registry`; a fresh copilot re-onboard is only needed to re-derive maps (the LLM path was not exercised
headless).

## 5. Verification

- `pytest tests/test_type_compat.py` — 15 passed (compatible / incompatible / unknown, incl. the two wire cases).
- `pytest tests/test_input_map_type_compat.py` — 4 passed (commit hard-reject: object→string subfield,
  array<object>→array<string>, compatible passes, open target tolerated).
- `pytest tests/test_type_compat_derivation.py` — 2 passed (derivation warning raised / not raised).
- `process-registry` full: **358 passed**. `agent-runtime` full: **343 passed, 4 skipped** (the relaxed wire
  schema did not break the real-server integration tests).
- Wire MCP-stub: schema import + compliance self-check OK; 10 server tests pass (2 failures —
  `assess_beneficiary`, `sdk_tools_list` — are **pre-existing**, confirmed identical on the committed schema; an
  unrelated mcp-SDK/env issue).
- Live e2e: relaxed `screen_party`(object account)→clear and `notify_parties`(object recipients)→performed
  (in-process real-SDK calls); full pipeline `pi-b29c877436474015` → `End_Resolved`. `stan-dine` unaffected
  (its screen `screen_allergens` produced its artifact; the wire schema change is wire-only, and the guard
  flags only definite mismatches — no dine-in false block).
- No git write ops; tree left dirty.

## 6. Open / for the reviewer

- **Faithfulness assumption:** the commit guard resolves the TARGET from the registered input artifact schema,
  which by ADR-025 introspection mirrors the tool `inputSchema`. If a future introspector were to *widen* a
  nested type when registering (e.g. open up `party.account`), the commit guard would see a permissive target
  and not flag it (the runtime would still enforce the real tool schema). Worth a guard test at the introspector
  if that ever changes.
- **Artifact-sourced derivation warnings:** the soft (reconcile) warning only checks trigger-sourced fields
  (the trigger schema is in hand there); artifact-sourced fields are covered by the commit gate. Fine as-is;
  noted for symmetry.
- To make the guard live, rebuild `process-registry`. The `wire-stan` pack currently active was onboarded before
  the reference fix; it runs green now because the reference fix relaxed the contract. A re-onboard would
  re-derive its maps and (with the guard live) confirm zero incompatibilities.
