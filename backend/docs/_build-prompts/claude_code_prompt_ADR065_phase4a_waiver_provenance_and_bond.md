# Claude Code prompt — ADR-065 P4a: waiver provenance + the capability bond (contracts + registry)

Fourth phase of **ADR-065**, first half. P1 (registry), the rebind guard, P2 (runtime), the assist-ordering
correction and P3 (webui) are all shipped and reviewed. This phase closes the one **known** gap the P1 follow-up
report named, and adds the provenance the audit payload needs. **P4b** follows separately: the GLEA audit
payload, the ACH fixture migration off mislabeling, the Playwright journey, and the wizard-ReviewStep summary
gap. Read the ADR (**Parts A, B and F**) and
`backend/docs/_build-reports/claude_code_prompt_ADR065_phase1_followup_waiver_rebind_guard_report.md` §5 first.

## Why

The P1 follow-up made the copilot unable to move a waiver onto a capability its justification never described.
But as that report states plainly, the resulting guarantee is **registry-emission-side, not a signature**:

> Nothing cryptographically binds the justification text to the capability id; a hand-edited manifest committed
> out-of-band could still carry a mismatched waiver.

Stage 4 re-checks *load-bearingness* on every validate — is this waiver doing work — but never *correspondence*:
is this waiver about **this** capability. So a manifest that did not come through the wizard can still pair a
benign justification ("idempotent status handback") with `execute_payment`, and it validates clean.

Second gap: a waiver records **what** was allowed and **why**, but not **who** allowed it or **when**. For the
control that authorises a machine to act on the world unsupervised, that is the missing half of the audit trail —
and P4b's GLEA payload has nothing to carry without it.

## Deliverable 1 — provenance + bond on the waiver, stamped SERVER-side

Extend `SideEffectWaiver` (`libs/amendia_contracts/amendia_contracts/process_pack.py`) with three **optional**
fields: `waived_by`, `waived_at`, `waived_capability_id`. Optional, because a waiver written before this phase
(there are such waivers in dev sessions) must still parse — see Deliverable 3.

**The client does not send them; the server stamps them.** `set_bindings` derives all three from the
authenticated principal, the clock, and the binding's own `capability_ref` at the moment the waiver is written.
Two reasons this matters more than it looks:

- The bond is then **correct by construction** — the server cannot stamp a capability id the binding does not
  have, so the field can never disagree with reality at creation time. Only a later hand-edit can break it, which
  is exactly the threat Deliverable 2 catches.
- P3 just shipped the UI. Requiring the client to send provenance would mean changing it again and would let a
  caller assert its own `waived_by` — which is not provenance, it is a claim.

Stamp `waived_capability_id` as the **bare capability id** (before `@`), consistent with `_bare_cap_id` in
`reconcile.py` and `bareCapId` in `WaiverAffordance.tsx`, so a version-range bump does not break the bond.

**`waived_by` / `waived_at` record who wrote the justification, at `set_bindings` — not who published the
pack. [confirm]** They are different facts and both are worth having: the author of a justification and the
publisher of a pack can be different owners, and it is the author's reasoning the waiver carries. Pack publish
already has its own actor in the audit trail; P4b will carry both.

## Deliverable 2 — stage 4 verifies the bond

In `pack_validator.py` stage 4, where the waiver is already resolved: when `waived_capability_id` is **present**
and does not match the bare capability id of what the binding actually resolves to → `report.error`, new code
`side_effect_waiver_capability_mismatch`, with a message naming both ids. This is the only check that can catch a
manifest which never came through the registry.

Which capability to compare against: for a capability executor, the executor's; for a human executor with a
side-effectful assist, the **assist's** (that is what the waiver authorises there — see the amended Part G).
Handle a binding where both could apply and say in the report how you resolved it.

Mirror it in `services/onboarding.py::_check_hitl_guard` so assemble and validate agree, as P1 established.

## Deliverable 3 — absent provenance is legacy, not invalid

A waiver with no `waived_capability_id` must still validate — it is a pre-P4a waiver, not a forgery, and failing
it would break sessions and dev packs created during P1–P3. Emit a **warning**
(`side_effect_waiver_unbonded`) so the gap is visible and the pack can be re-saved to acquire provenance, but
never an error.

Note in the report whether re-saving an affected binding through `set_bindings` naturally backfills the fields —
it should, since the server stamps on write — so operators have an obvious remedy.

## Deliverable 4 — make the bond hold end to end

Verify and test the full path: `set_bindings` stamps → session round-trip → assemble emits all four fields on the
manifest → `from-pack` re-edit rehydrates them → the copilot rebind guard still drops the whole waiver
(provenance included) when the capability changes. That last one matters: a dropped-and-rewritten waiver must
acquire **fresh** provenance, never inherit the old author or the old bond.

## Do not

- Do not make any of the three fields required, and do not reject a waiver that lacks them (Deliverable 3).
- Do not let a client set `waived_by` — reject or ignore it if sent, and say which you chose.
- Do not touch the runtime, GLEA, the webui, or the ACH fixture. P4b owns those.
- Do not change the justification rule, the waivable/non-waivable split, or any P1–P3 finding code.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- A waiver written through `set_bindings` carries `waived_by` (the authenticated owner), `waived_at`, and
  `waived_capability_id` (bare id) — none of them client-supplied.
- A hand-built manifest pairing a waiver with a **different** capability → `side_effect_waiver_capability_mismatch`,
  at both validate and assemble. Assert the message names both ids.
- The same manifest with a matching bond → validates clean, with the `side_effect_waived` warning as before.
- A waiver with no provenance → warning `side_effect_waiver_unbonded`, **not** an error; the pack still
  validates.
- The assist case: a waiver on a human binding is bonded to the **assist** capability, and a mismatch there is
  caught too.
- Rebind through the copilot → the new waiver (once written) carries fresh provenance; none of the old author,
  timestamp or bond survives.
- `pytest` green for process-registry and `libs/amendia_contracts`; agent-runtime and webui untouched (prove it).
  The contract gained fields, so **re-dump the OpenAPI snapshot and regenerate `registry.ts`** — the webui does
  not yet read the new fields (P4b), but the types must compile.
- **Reviewer note:** live only after `docker compose build process-registry`.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR065_phase4a_waiver_provenance_and_bond_report.md`
(uncommitted): (1) outcome one-liner; (2) the three fields and exactly where each is stamped; (3) how you
resolved which capability the bond compares against, especially for a human binding with an assist; (4) what
happens to a client that tries to send `waived_by`; (5) whether re-saving backfills legacy waivers; (6)
verification — commands, results, and the mismatch case by name; (7) for P4b: the final manifest shape of a fully
provenanced waiver, so the GLEA payload can be written against it.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Backend-only: `libs/amendia_contracts` +
`process-registry`. Server-stamped, never client-asserted — that distinction is the whole point of this phase.
Smallest change that turns an emission-side guarantee into one a manifest carries with it.
