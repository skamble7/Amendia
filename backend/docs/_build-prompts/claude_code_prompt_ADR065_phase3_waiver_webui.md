# Claude Code prompt — ADR-065 P3: the waiver in the UI (webui)

Third phase of **ADR-065**. P1 (registry), its rebind guard, P2 (runtime) and the assist-ordering correction are
all shipped and reviewed. The waiver is enforced everywhere and **surfaced nowhere** — no operator can create one,
and a waived step currently *disappears* from the review summary. This phase fixes both. Read the ADR
(**Part F** and the amended **Part G**) and the four `_build-reports/claude_code_prompt_ADR065_*` reports first.

## Why

Two problems, and the second is the dangerous one.

1. **No operator can set a waiver.** The contract, validator, assemble guard and runtime all honour
   `side_effect_waiver`, but nothing in the wizard writes it. Today the only way to get one is a hand-edited
   manifest — which is exactly the untraceable path ADR-065 replaced.
2. **A waived step is currently invisible.** `webui/src/features/copilot/humanize.ts:46-58` (`gatesOf`) filters
   `hitl_mode !== "none"`, so a binding that runs a real-world action with **no** human gate is silently dropped
   from the review summary rendered by `CopilotReview.tsx` and `CopilotSteppedReview.tsx`. The single
   highest-risk item in a pack is the one the reviewer never sees. That is backwards and it ships today.

## Read first

- `webui/src/features/registry/OnboardingWizard.tsx` — `HITL_MODES`/`HITL_RANK` (:37-38), `policyByCap`
  (:1248-1263), the pre-fill bump (:1486), `chooseExecutor`'s bump (:1549-1556), and the `disabled` option render
  (:1657). This is where `none` is currently unreachable for a side-effectful capability.
- `webui/src/features/copilot/humanize.ts:46-58` (`gatesOf`), `CopilotReview.tsx:71-77`,
  `CopilotSteppedReview.tsx:170-176` — the review summary that drops ungated steps.
- `webui/src/components/primitives.tsx:94-95` (`SideEffectBadge`) — the existing visual vocabulary for
  side-effectfulness; extend it rather than inventing a second one.
- `libs/amendia_contracts/amendia_contracts/process_pack.py` — `SideEffectWaiver.justification`, **≥20 chars
  after strip**, enforced at parse time. The UI mirrors this rule; the contract remains the authority.
- `backend/services/process-registry/app/validation/pack_validator.py` (stage 4) — the finding codes the UI must
  surface: `side_effect_waived` (warning), `side_effect_waiver_not_required`, `side_effect_requires_approve_actions`,
  `assist_side_effect_requires_waiver`.

## Deliverable 1 — set a waiver in the technical wizard (Bindings step)

Make `none` reachable for a side-effectful capability **only through an explicit waiver**, never by simply
picking it from the dropdown.

- The mode select's `disabled` logic (:1657) currently blocks anything below the floor. Below-floor modes become
  reachable only once the operator opens a waiver affordance for that binding.
- **The affordance is a justification, not a checkbox.** A textarea, required, with the ≥20-character rule
  mirrored client-side and a live character count; the Save/Continue path stays blocked until it is satisfied.
  A bare "I accept" toggle is explicitly rejected — the friction *is* the control, and the text is what lands in
  the audit trail.
- It must state plainly what is being waived: the capability id, that it performs a real-world action, and that
  it will run with **no human approval**. Do not soften this copy.
- Clearing the waiver re-applies the floor (the mode bumps back up), so the UI can never leave a below-floor
  binding without one.

## Deliverable 2 — the bump must not fight the waiver (same defect class as the copilot rebind hole)

`chooseExecutor` (:1549-1556) and the pre-fill (:1486) bump `hitl_mode` up to the floor whenever a capability is
selected. On a **waived** binding that bump would silently re-gate it — the exact bug the P1 follow-up fixed in
`reconcile.py`, one layer up.

Mirror the backend rule rather than inventing a UI-specific one:

- Capability **unchanged** ⇒ leave a waived binding's mode and waiver alone; do not bump.
- Capability **changed** ⇒ **drop the waiver** and re-apply the floor, with a visible notice that the waiver was
  cleared because the capability changed and must be re-written for the new one. Never silently carry a
  justification onto a different capability.

Compare on the **bare capability id** (before `@`), consistent with `_bare_cap_id` in `reconcile.py`.

## Deliverable 3 — a waived step must be the LOUDEST row, not a missing one

Fix `gatesOf` so a waived binding is **not** filtered out. Waived steps render as a distinct, prominent risk row
wherever gates are summarised (`CopilotReview`, `CopilotSteppedReview`, and the wizard's own review step),
carrying the capability and the justification text, visually distinguishable from an ordinary gate — this is not
a gate, it is the absence of one.

Sanity check for the whole deliverable: **a reader skimming the review must be able to answer "what does this
process do without asking me?" without expanding anything.**

## Deliverable 4 — waivers on the pack detail page

List a pack's waivers on its detail page — element, capability, justification. Visible to any authenticated
viewer; creating and editing stays owner-gated by the existing Registry gating (no new authorization surface).
Transparency is the point: a non-owner auditor should be able to see what a pack does un-gated.

## Deliverable 5 — set a waiver in the copilot review too

An operator reviewing a copilot-generated pack must be able to waive there, rather than abandoning the copilot
for the technical wizard. **The operator may set it; the LLM may never propose, suggest or pre-fill one** — do
not add a mutation kind, a proposal field, or any copy that invites the model to recommend a waiver
(ADR-065 Part C). Reuse the same affordance component as Deliverable 1 so the justification requirement and the
copy are identical on both paths.

Verify the interaction with the existing guard: a waiver set in copilot review must survive a subsequent chat
turn that does not touch that binding, and must be dropped if that turn rebinds or re-gates it
(`reconcile.py::_waiver_drop_reason`). Add a test.

## Deliverable 6 — one backend string (the only backend edit permitted here)

`pack_validator.py`'s `side_effect_waived` warning reads *"runs a side-effectful capability WITHOUT a human gate
(hitl '<mode>')"*. For the **assist** case that is false — there is a human gate, the assist simply precedes it.
Reword so both cases are accurate, since P3 puts this text in front of the operator. No logic change.

## Do not

- Do not change the contract, the validator's logic, the runtime, or the copilot guard beyond Deliverable 6's
  string.
- Do not add a way for the LLM to create, suggest or pre-fill a waiver.
- Do not add a bare-toggle waiver anywhere, and do not weaken the ≥20-character rule client-side.
- Do not let the UI be the only thing enforcing anything — the contract and validator remain the authority; the
  client-side mirror exists for feedback, not for safety.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- A side-effectful capability can be taken to `none` in the wizard **only** by writing a ≥20-char justification;
  the resulting pack assembles, validates clean, and the report carries `side_effect_waived`.
- Clearing the waiver re-applies the floor; changing the capability drops the waiver with a visible notice
  (Deliverable 2) — assert both.
- A waived binding appears in every review summary as a prominent risk row with its justification — assert it is
  **present**, not merely un-crashed (the current bug is a silent omission, so a test that only checks rendering
  succeeds would pass today).
- Pack detail lists waivers; a non-owner can see them and cannot edit them.
- A waiver can be set in copilot review, survives an unrelated chat turn, and is dropped on rebind/re-gate.
- `tsc --noEmit`, `npm run build`, and `vitest` green. Backend suites unchanged except Deliverable 6's string —
  prove process-registry and agent-runtime are otherwise untouched.
- A Playwright journey is **not** required this phase; note in the report what one would assert so it can be
  added alongside the P4 fixture migration.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR065_phase3_waiver_webui_report.md` (uncommitted):
(1) outcome one-liner; (2) the affordance — where it lives, what it demands, and the exact copy shown to the
operator (quote it; this is the text that justifies an ungated real-world action); (3) how Deliverable 2 decides
to keep vs. drop a waiver, and how it tells the operator; (4) what the review summary now renders for a waived
step, before/after; (5) the copilot-review path and its guard interaction; (6) verification — commands, results,
and specifically the assertion that a waived step is *present* in the summary; (7) what a Playwright journey
should cover, for P4.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. webui only, plus Deliverable 6's one string. Reuse the
existing `SideEffectBadge` vocabulary and the wizard's existing inline-edit machinery rather than building new
patterns. The operator-facing copy matters as much as the code here: this is the screen where someone decides a
machine may act on the world unsupervised, and the words should make that decision feel like what it is.
