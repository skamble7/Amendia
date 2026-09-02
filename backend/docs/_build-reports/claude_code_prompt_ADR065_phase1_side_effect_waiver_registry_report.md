# ADR-065 Phase 1 — Side-Effect Waiver (contracts + registry validation)

**Scope:** contract model + registry validation only. No runtime enforcement (P2), no webui feature
code (P3), no GLEA audit / ACH fixture migration (P4). Backend-only: `libs/amendia_contracts` +
`backend/services/process-registry`. Tree left dirty — no git writes; the operator owns commits.

**Outcome: DONE and green.** The human gate on a side-effectful capability is now *default-on but
waivable, per binding, with a required written justification*. A no-waiver pack validates exactly as
before; a waived floorless side-effectful binding at `hitl none` validates clean and emits a
`side_effect_waived` warning; every dead/illegitimate waiver is rejected with a clear message.

---

## 1. The contract (D1)

`libs/amendia_contracts/amendia_contracts/process_pack.py`:

- **`SideEffectWaiver`** — a single required field `justification: str`. A pydantic
  `field_validator` strips and rejects anything shorter than **20 characters** at parse time
  (`ValidationError`). There is **no boolean / justification-free form** — a waiver cannot exist
  without a substantive written reason. Stored stripped.
- **`Binding.side_effect_waiver: Optional[SideEffectWaiver] = None`** — purely additive. Absent ⇒
  today's behaviour, byte-for-byte.

This is the whole wire contract. Nothing about how `side_effect` is inferred, the `HitlMode` ladder,
`hitl_rank`, or runtime behaviour was touched.

---

## 2. Finding codes introduced (severity + waivability)

All in `app/validation/pack_validator.py` (stage 4 mirrored into `onboarding._check_hitl_guard` and
`onboarding.set_bindings` so assemble-time and pack-validation-time agree).

| Code | Sev | Waivable? | Fires when |
|---|---|---|---|
| `side_effect_requires_approve_actions` | error | **yes** | capability executor is side-effectful and binding is below the approve_actions floor, no waiver present |
| `assist_side_effect_requires_approve_actions` | error | **yes** | the **human-assist** descriptor (D3) is side-effectful and below floor, no waiver present |
| `side_effect_waived` | **warning** | — | a load-bearing waiver *is* present; message carries element id + capability id + the justification text |
| `side_effect_waiver_not_required` | error | — | dead waiver: on a read_only capability, or on a binding already at/above the floor (nothing to waive) |
| `hitl_below_capability_floor` | error | **no** | capability's own `min_hitl_mode` floor — a stricter platform-set floor, never waivable |
| `hitl_none_on_human_executor` | error | **no** | a human executor bound at `hitl none` (would crash at runtime — see D3) |
| `multi_instance_side_effect_unsupported` | error | **no** | a side-effectful capability used as a multi-instance host (D4) — waiver or not |
| `side_effect_downgraded_from_inference` | **warning** | — | operator set `read_only` on a tool whose resolved output carries the ack shape (D7) |
| `sod_element_ungated` | **warning** | — | a `distinct_actor` SoD rule names an element that is waived / left at `hitl none` (D7) |

`deep_agent_requires_hitl` and `hitl_role_missing` are unchanged and **not** waivable (verified by
`test_deep_agent_validation::test_waiver_cannot_un_gate_a_deep_agent`).

---

## 3. Deliverable 3 premise — CONFIRMED empirically

**Premise (from the ADR):** the human-assist hole — a `human` executor's assist descriptor is
side-effectful, but stage 4 skipped the side-effect rule for human executors; and a human executor at
`hitl none` crashes at runtime.

**Confirmed, with evidence:**
- Stage 4 previously set `desc = None` for a human executor and `continue`d, so the
  side_effectful ⇒ approve_actions rule never ran against the assist descriptor. A failing test
  (`assist_side_effect_requires_approve_actions not in errs`) demonstrated the hole; it now asserts
  the error **is** raised and the waiver clears it
  (`test_pack_validator::test_assist_side_effect_now_caught_and_waiver_clears`).
- Runtime crash confirmed by code, not speculation: `agent-runtime/.../hitl.py`'s `ALLOWED_DECISIONS`
  has keys `{review_after, approve_result, approve_actions, manual}` — **no `none` key** — so
  `allowed_decisions_for("none")` raises `ValueError`. `task_runner` routes every human executor
  through `_run_manual → interrupt()`, which calls that function. A human executor at `none` therefore
  raises at runtime. Stage 4 now rejects it up front as `hitl_none_on_human_executor`
  (`test_human_executor_at_none_rejected`).

The same waiver covers the assist side-effect case; the human-none crash is **not** waivable (it is a
correctness floor, not a policy floor).

---

## 4. Deliverable 7 — where the inference signal was reachable (deviation noted)

**`side_effect_downgraded_from_inference` (mislabel warning).** The ADR asked to warn when an operator
labels a tool `read_only` but its output still carries the ack shape — "put it where the signal
exists." The natural home would be `set_capabilities`, at the point the operator asserts the label.
That surface **only has an error channel, no warning channel**, and re-plumbing it to carry
non-blocking warnings was out of scope for a contract+validation phase.

**Deviation, deliberate:** the warning is raised in the validator instead
(`_validate_side_effect_labeling`), which **recomputes `carries_ack_shape(...)` on the resolved output
artifact schema** of each read_only capability/assist. This is a faithful reconstruction of the same
signal at a later, read-only point — the operator still sees the warning against the pack, just at
validate time rather than label time. Covered by
`test_read_only_with_ack_shape_output_warns` (which uses `schema_repo.insert(...)` directly to seed an
ack-shaped output past the backward-compat registration gate).

`sod_element_ungated` sits in stage 7 (triage/SoD), where the SoD rules and the per-element hitl modes
are both already in scope — no signal reconstruction needed.

---

## 5. Round-trip (D5, D6) — waiver survives the full path

`set_bindings → StagedBinding → session → assemble → manifest → from-pack → copilot`, verified end to
end:

- **Session models (D6):** `StagedBinding` and `BindingInput` carry `side_effect_waiver`;
  `set_bindings` persists it; `_compose` emits `binding_doc["side_effect_waiver"] =
  {"justification": ...}` on the manifest; `_staged_binding_from_manifest` rehydrates it from a pack.
  (`test_onboarding::test_waiver_survives_assemble_manifest_and_from_pack`.)
- **Copilot (D5):** **no `set_waiver` mutation was added** — `MUTATION_KINDS` stays a closed vocabulary
  with no waiver verb. `_clamp_hitl` is now waiver-aware: on a binding that already carries a waiver it
  leaves the mode/role alone and re-attaches the operator's waiver rather than clamping it up; it never
  creates a waiver. (`test_copilot_chat::test_copilot_chat_preserves_operator_waiver` — wizard waives →
  copilot chat-edits → waiver survives.)

**Manifest shape (for P2 hand-off):** a waived binding serialises as
`binding.side_effect_waiver = {"justification": "<text>"}`. That is the shape `bundle.py` will read in
P2 to thread the waiver onto `NodeContext` for the runtime gate. It is intentionally an object (not a
bare string / bool) so P2 can add fields (waived-by, waived-at) without a wire break.

---

## 6. Verification

Commands run from each project root; `uv run --extra dev pytest` (process-registry, agent-runtime),
`uv run --with pytest pytest` (amendia_contracts, amendia_bpmn).

| Suite | Result | Note |
|---|---|---|
| `process-registry` | **419 passed** | baseline 405 → +14 net new tests |
| `libs/amendia_contracts` | **9 passed** | new `tests/test_side_effect_waiver.py` (dir did not exist before) |
| `libs/amendia_bpmn` | **198 passed** | unaffected; run as a dependency sanity check |
| `agent-runtime` | **green (exit 0)** | consumes the additive contract; **working tree unchanged** (`git status --short backend/services/agent-runtime` empty) — proves untouched |
| webui `tsc --noEmit` / `npm run build` | **green** | 2165 modules, built 1.79s |

**Per rejection case (all asserted green):**

- floorless side-effectful at `none` **with** waiver → clean + `side_effect_waived` warning
  (`test_waiver_allows_floorless_side_effectful_at_none`)
- waiver on a read_only capability → `side_effect_waiver_not_required` (`test_waiver_on_read_only_is_dead`)
- waiver on an already-gated binding → `side_effect_waiver_not_required` (`test_waiver_on_already_gated_is_dead`)
- waiver cannot pass `min_hitl_mode` → still `hitl_below_capability_floor` (`test_waiver_cannot_pass_min_hitl_mode`)
- waiver cannot un-gate a deep agent → still `deep_agent_requires_hitl` (`test_waiver_cannot_un_gate_a_deep_agent`)
- human executor at `none` → `hitl_none_on_human_executor` (`test_human_executor_at_none_rejected`)
- side-effectful multi-instance host **with** waiver → still `multi_instance_side_effect_unsupported`
  (`test_multi_instance_side_effect_blocked_even_with_waiver`)
- assist side-effect caught + cleared by waiver (`test_assist_side_effect_now_caught_and_waiver_clears`)
- read_only + ack-shaped output → `side_effect_downgraded_from_inference` (`test_read_only_with_ack_shape_output_warns`)
- SoD over an ungated element → `sod_element_ungated` (`test_sod_over_ungated_element_warns`)

**Seed packs unchanged:** `wire-repair-standard`, `wire-repair-agentic`, `payment-compensation`
validate clean (their seed side-effectful caps all carry `min_hitl_mode = approve_actions`, a
non-waivable floor, so nothing about them changed). The absolutism tests that previously asserted
"side_effect is never waivable" were **flipped, not deleted** (`test_pack_validator` ~139/355,
`test_onboarding` ~311).

**Test-fallout fixed (not masked):** 7 human-task tests (`test_human_task_inputs`,
`test_human_task_outputs`, `test_refine_artifact`) previously bound human executors implicitly at
`hitl none` (the `BindingInput` default). The new `hitl_none_on_human_executor` rule correctly rejected
them — proving the D3 runtime-crash premise. Fixed by binding those human tasks at
`hitl_mode="manual", hitl_role="role.server"` (the real, valid configuration), not by relaxing the rule.

**OpenAPI / webui types:** `webui/openapi/registry.json` re-dumped
(`python scripts/dump_openapi.py`; `side_effect_waiver` appears 10×); `webui/src/api/gen/registry.ts`
regenerated from that offline snapshot (gen-api.mjs sources registry types from
`../openapi/registry.json`, not a live fetch). `npm run gen:api:check` cannot pass against the *live*
stack until `docker compose build process-registry` rebuilds the image — the generated types are green
in the working tree; they are not yet live in the running stack.

---

## 7. Left for later phases

- **P2 (runtime enforcement):** `bundle.py` reads `binding.side_effect_waiver.justification` off the
  manifest, threads it onto `NodeContext`, and the runtime gate honours it. No agent-runtime code was
  touched here.
- **P3 (webui):** surface the waiver in the wizard (justification field, ≥20-char client-side mirror of
  the contract validator) and in copilot review. The generated types compile; no feature code uses the
  field yet.
- **P4 (GLEA):** the waiver decision + justification into the audit payload; migrate the ACH fixture.

## 8. Follow-ups / notes

- The `side_effect_downgraded_from_inference` warning is recomputed at validate time rather than raised
  at label time (§4). If P3 adds a warning channel to `set_capabilities`, consider moving it upstream
  so the operator sees it the moment they mislabel.
- Manifest waiver shape is an object (§5) precisely so P2/P4 can add provenance fields without a wire
  break — recommend `waived_by` / `waived_at` land in P4 alongside the audit payload.
