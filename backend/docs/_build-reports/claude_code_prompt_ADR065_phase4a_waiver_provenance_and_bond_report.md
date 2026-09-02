# ADR-065 P4a — waiver provenance + the capability bond (contracts + registry)

**Outcome: DONE and green.** A side-effect waiver now carries **who** wrote it, **when**, and **which capability**
it authorises — all stamped server-side, never client-asserted — and stage 4 rejects a manifest whose waiver is
bonded to a different capability. This turns the P1 registry-emission-side guarantee into one the manifest carries
with it. Backend-only: `libs/amendia_contracts` + `process-registry`. Tree left dirty.

## 1. The three fields and where each is stamped

`SideEffectWaiver` (`process_pack.py`) gained three **optional** fields: `waived_by: Optional[str]`,
`waived_at: Optional[datetime]`, `waived_capability_id: Optional[str]`. Optional so a pre-P4a waiver still parses
(Deliverable 3).

All three are stamped in one place — `onboarding.py::set_bindings`, via the new `_stamp_waiver(b, prior, owner)`,
at the moment a binding is written:

- **`waived_capability_id`** — the **bare** id (`ref.split("@",1)[0]`) of the binding's OWN capability at write
  time (`_bond_cap_ref`): the executor's capability, or — for a human executor — its `assist_capability_ref`
  (amended Part G). Correct by construction: the server cannot stamp a capability the binding does not have.
- **`waived_by`** — the authenticated `owner` passed to `set_bindings`.
- **`waived_at`** — `utcnow()`.

`_compose` emits all four onto the manifest (`model_dump(mode="json", exclude_none=True)`); `from-pack`
rehydrates them (`SideEffectWaiver.model_validate` already accepts the full dict). Verified end to end
(Deliverable 4).

**`waived_by` / `waived_at` record who wrote the justification at `set_bindings`, not who published the pack —
[confirmed].** They are different facts: the justification's author and the pack's publisher can differ, and it is
the author's reasoning the waiver carries. Pack publish keeps its own actor; P4b's GLEA payload can carry both.
Nuance: an **unchanged** re-save preserves the original `waived_by` + `waived_at` (an unrelated Bindings edit must
not restamp a waiver it did not touch); a **new or changed** justification is stamped fresh — so a
dropped-and-rewritten waiver (a rebind) always acquires fresh provenance.

## 2. Which capability the bond compares against

A binding has exactly **one** side-effect subject (stage 4 already computes it): for a capability executor, the
executor's capability; for a human executor with a side-effectful assist, the **assist** (amended Part G). There
is no "both" case — executor type is exclusive, so a binding is never simultaneously a capability executor and a
human-with-assist. The bond check therefore compares `waived_capability_id` against `subjects[0].capability_id`
(the single subject). The assist path is exercised by `test_assist_waiver_bond_mismatch_rejected`, whose message
names the **assist** id (`cap.payment.draft_rfi`), not the human role.

## 3. Deliverable 2 — the mismatch check, and where the mirror actually lives

`pack_validator.py` stage 4: when `waived_capability_id` is present and ≠ the subject's bare id →
`report.error("side_effect_waiver_capability_mismatch", …)` naming **both** ids. Absent bond on a load-bearing
waiver → `report.warning("side_effect_waiver_unbonded", …)` (Deliverable 3), never an error.

**How I resolved the `_check_hitl_guard` "mirror":** I did **not** add a bond check to `_check_hitl_guard`, and
that is deliberate. The set_bindings path **cannot produce a mismatch** — `_stamp_waiver` ignores any client-sent
bond and re-stamps the binding's own capability, so what gets persisted is always correct. A mismatch is only
reachable via a **hand-built manifest** that bypasses set_bindings, which reaches the registry at **activate** →
`PackValidator`. And **assemble** also runs `PackValidator` (not `_check_hitl_guard`) on the composed manifest. So
assemble and activate/validate agree because they share the same check — adding a `_check_hitl_guard` bond guard
would only reject a client-sent bond we are about to overwrite anyway, contradicting "ignore client provenance."
The floor-rule mirror P1 added stays as-is.

## 4. What happens to a client that sends `waived_by` (or a bond)

**Ignored.** `_stamp_waiver` reconstructs the waiver from `justification` alone plus server facts; any client-sent
`waived_by` / `waived_at` / `waived_capability_id` is discarded. `test_side_effect_requires_approve_actions` sends
`waived_by="attacker"` + a wrong `waived_capability_id="cap.payment.execute_return"` and asserts the persisted
waiver is stamped `waived_by=OWNER`, `waived_capability_id="cap.payment.screen_party"` (the binding's own
capability) — neither client value survives. Ignore, not reject: a client can't forge provenance, and a
mismatched bond it sends is simply corrected rather than surfaced as its error.

## 5. Re-saving backfills a legacy waiver

Yes. A pre-P4a waiver (no `waived_by`) is not "already provenanced", so `_stamp_waiver` takes the fresh-stamp
branch on the next `set_bindings` — stamping `waived_by` (current owner), `waived_at` (now), and the bond. So the
operator remedy for a `side_effect_waiver_unbonded` warning is simply to re-save the binding.

## 6. Verification

| Check | Result |
|---|---|
| `libs/amendia_contracts` | **11 passed** (+2: optional-fields-parse, provenance round-trip) |
| process-registry | **427 passed** (+6 P4a; incl. the re-dumped OpenAPI snapshot test) |
| agent-runtime | **exit 0** — untouched by P4a; green against the additive contract |
| webui | `tsc` + `build` + `vitest` (**210**) green; P4a changed only `openapi/registry.json` + `api/gen/registry.ts` (regenerated), no feature code |

The mismatch case by name — `test_waiver_capability_mismatch_rejected_naming_both_ids`: a manifest binding
`Task_RecordResolution` (side-effectful `cap.payment.record_resolution`) with a waiver bonded to
`cap.payment.execute_return` → `side_effect_waiver_capability_mismatch`, message contains **both**
`cap.payment.execute_return` and `cap.payment.record_resolution`. `test_waiver_matching_bond_is_clean` (correct
bond → clean + `side_effect_waived`, no mismatch/unbonded); `test_waiver_unbonded_is_a_warning_not_an_error`
(no bond → warning, `report.ok`); `test_assist_waiver_bond_mismatch_rejected` (assist bond); the round-trip
(`test_waiver_survives_assemble_manifest_and_from_pack`) now asserts all four fields survive
set_bindings → assemble → commit → from-pack. **Rebind → fresh provenance** is covered by the existing
`test_copilot_chat_drops_waiver_on_rebind` (the whole waiver, provenance included, is dropped to `None`) combined
with `_stamp_waiver`'s fresh-stamp-on-new — a rewritten waiver cannot inherit the old author, timestamp, or bond.

OpenAPI snapshot re-dumped (`scripts/dump_openapi.py`, 231723 bytes, 4 provenance-field references);
`registry.ts` regenerated from the offline snapshot (`npm run gen:api` → `✓ registry`; the 4 live-service
fetch failures are the unrelated stack, not the registry types). Not live until `docker compose build
process-registry`.

## 7. For P4b — the manifest shape of a fully-provenanced waiver

A binding's `side_effect_waiver` on the emitted manifest (write the GLEA payload against this):

```json
"side_effect_waiver": {
  "justification": "Idempotent status handback to the orchestrator; nothing to gate here.",
  "waived_by": "usr-owner",
  "waived_at": "2026-09-01T12:00:00Z",
  "waived_capability_id": "cap.payment.record_resolution"
}
```

A **legacy** waiver carries `{"justification": …}` only (no provenance keys) and rides a
`side_effect_waiver_unbonded` warning — P4b's GLEA payload should treat the three provenance fields as optional and
degrade gracefully. P4b still owns: the GLEA audit payload (both the waiver author and the pack publisher), the ACH
fixture migration off mislabeling, the Playwright journey, and the wizard-ReviewStep summary gap.
