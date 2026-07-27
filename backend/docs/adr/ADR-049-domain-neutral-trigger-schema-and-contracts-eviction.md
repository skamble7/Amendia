# ADR-049 — Domain-neutral trigger schema (first-class per-pack input) and eviction of domain payload contracts

**Status:** Accepted — shipped 2026-07-27
**Date:** 2026-07-27
**Context owner:** Sandeep Kamble
**Relates:** ADR-047 (D1 — the pack's declared trigger artifact; platform domain-neutrality), ADR-025 (the
`OnboardingSession` state machine), ADR-027 (triage predicates + schema-aware validation), ADR-048
(capability-IO `input_map`), the Process Onboarding Guide + the MCP-backed Onboarding Runbook.

> Reconstructed from the shipped implementation. Replace with the canonical project-doc body if it differs.

## Context

After ADR-047 made the **runtime** domain-neutral, two residual couplings still tied the *platform* to the
wire/payments domain:

1. **The onboarding wizard learned the trigger shape from the wire sample envelopes.**
   `OnboardingSession.trigger_fields` — the `{dotpath: json_type}` map that drives the Triage step's field
   picker and its schema-aware predicate validation — was computed from `infer_field_types(load_sample_envelopes())`,
   and `load_sample_envelopes()` read the hardcoded `SEED_DIR/sample-exception` directory (the **wire** samples;
   `services/onboarding.py:269`, `deps.py:70`, `routers/packs.py:39`). A non-wire pack (e.g. restaurant
   dine-in) therefore had **no typed field picker** unless the deployment happened to ship matching sample
   envelopes, and the picker's vocabulary was implicitly the wire envelope's. `ProcessPack.trigger:
   Optional[ArtifactRef]` already existed (ADR-047 D1, `process_pack.py:284`) but the wizard never set it and
   `_compose` never emitted it — so triage ignored it.

2. **Two domain payload contracts lived in the shared platform lib.** `amendia_contracts.wire_exception` (the
   wire-exception envelope) and `amendia_contracts.order_ticket` (the dine-in order ticket) sat in
   `libs/amendia_contracts`, imported **only** by `stub_exception_generator`. A platform contracts lib that
   ships concrete domain payload shapes is the same domain leak ADR-047 removed from the runtime, one layer up.

## Decision

### D1 — The trigger schema is a first-class, per-pack, operator-declared input

- The onboarding wizard gains a **declare-trigger** action: `PUT /onboarding/{id}/trigger` with
  `DeclareTriggerRequest{artifact_key, version, title, description?, json_schema}`. The operator provides the
  trigger artifact id `art.<domain>.<name>` and its JSON-Schema (the trigger is a **process input**, not a tool
  output, so it cannot be MCP-introspected — it is authored/pasted). It is stored on the session as
  `trigger_artifact: StagedArtifact` — the same shape used for introspected capability schemas — and validated
  (`art.<domain>.<name>` id + an object schema with a `properties` map).
- `session.trigger_fields` is computed by **flattening the declared JSON-Schema** (`flatten_schema_fields`:
  dot-paths + JSON types, recursing nested objects; `integer` folds to `number` to match the sample-derived
  vocabulary; arrays/enums are leaves) — **not** from sample envelopes. It **falls back** to
  `infer_field_types(sample_envelopes)` only when no trigger is declared (opaque if there are none).
- The same `trigger_fields` drive the schema-aware triage validation (`set_triage`) and are surfaced by the
  Triage step's field picker + type-valid operators.
- At assemble/commit, `_compose` **registers** the trigger schema like any staged artifact, lists it among the
  pack `artifacts`, and emits it as the manifest's `ProcessPack.trigger` (a pinned `ArtifactRef`).
- Declaring/replacing the trigger is an **enrichment, not a new state**: callable once the process is known
  (≥ `bpmn_attached`); because the trigger fields change, it clears any authored triage + downstream and
  regresses to `bindings_set`.
- Net: **no `SEED_DIR/sample-exception` dependency** for a pack that declares its trigger.

### D2 — Evict the domain payload contracts from `amendia_contracts`

- `wire_exception.py` and `order_ticket.py` move to `stub_exception_generator/app/contracts/` (classes +
  `SCHEMA_VERSION` constants identical); the stub imports them from `app.contracts.*`. `libs/amendia_contracts`
  holds only **generic platform contracts**. The runtime never imports a domain trigger type — it validates the
  fetched trigger payload against the pack's declared schema (ADR-047 D1), treating it as opaque otherwise.

## Consequences

- **Domain-neutral onboarding.** Any pack declares its own trigger; the wizard picker and triage authoring work
  off that schema. The restaurant dine-in pack onboards end-to-end — declare `art.dining.order_ticket` → the
  picker offers `order_type / dietary_flags / party_size / requested_items / seated_at / table / tender /
  ticket_id` → author `order_type == "dine_in"` — with zero wire coupling and no sample-exception dependency.
- **The wire pack is unchanged.** It is seeded (a hand-authored manifest, no declared trigger), so
  `trigger_fields` falls back to the deployment sample envelopes and its triage still validates against the
  envelope fields.
- **`amendia_contracts` is domain-free.** The platform lib no longer ships payment/dining payload shapes; only
  the producer (`stub_exception_generator`) and any typed consumer carry them.
- **Backward-compatible.** `ProcessPack.trigger` stays optional; a pack with no declared trigger is treated as
  an opaque object (any JSON accepted), exactly as before. `PackValidator`'s triage stage degrades to
  structural-only when neither a declared trigger nor samples are available.
