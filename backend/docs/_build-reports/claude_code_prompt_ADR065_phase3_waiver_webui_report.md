# ADR-065 P3 — the waiver in the UI (webui)

**Outcome: DONE and green.** An operator can now create a side-effect waiver (in the technical wizard and, via the
same component, the copilot stepped review) by writing a justification — never a toggle — and a waived step is now
the LOUDEST row in every review summary instead of a silently dropped one. Pack detail lists a pack's waivers to
any viewer. webui only, plus Deliverable 6's one backend string. Tree left dirty.

## 1. The affordance — where it lives and what it demands

`webui/src/features/registry/WaiverAffordance.tsx` (shared): a collapsed **“Waive the human gate…”** button →
expands a **required textarea** with a live character count and the ≥20-char rule mirrored client-side
(`WAIVER_MIN_CHARS = 20`, mirroring the contract's parse-time floor). The **“Waive the gate”** button stays
disabled until the trimmed text reaches 20 chars. There is no toggle form. It is used by the wizard Bindings step
(D1) and, because `CopilotSteppedReview` re-composes that same `BindingsStep` at its Bindings step, by the copilot
review too (D5) — one component, identical requirement and copy on both paths.

Exact operator-facing copy (the text that justifies an ungated real-world action):

> **Waive the human gate on `<cap.id>`**
> `<cap.id>` performs a **real-world action**. Waiving lets it run with **no human approval**. Write why it is
> safe to run unsupervised — this justification is recorded in the audit trail.

And the waived-at-rest summary (also the loud row elsewhere): **“Runs with no human approval — waived”** +
“`<cap.id>` performs a real-world action and will run automatically, unsupervised.” + the quoted justification.

**How `none` is reached:** `policyByCap` now carries `minFloor` (the non-waivable `min_hitl_mode` rank) alongside
`floor`. The HITL-mode `<select>`'s disabled logic uses `effectiveFloorOf(row)` = `waiver ? minFloor : floor`, so
below-floor modes (incl. `none`) are selectable **only** once a waiver exists. Setting a waiver drops the gate to
that floor (usually `none`), making the waiver load-bearing; clearing it re-applies the full floor
(`hitl_mode` bumps back up). Raising the mode back to/above the floor via the select auto-clears the now-dead
waiver, so mode and waiver never contradict.

## 2. Keep vs. drop on capability change (D2) — same defect class as the copilot rebind hole

`chooseExecutor` (Bindings) compares the **bare capability id** (before `@`, via `bareCapId`, consistent with
`reconcile.py::_bare_cap_id`). Capability **unchanged** → the waiver and mode are left alone (a kept waiver owes
only `minFloor`, so it is not bumped). Capability **changed** → the waiver is **dropped** (`side_effect_waiver:
undefined`), the full floor is re-applied, and a visible amber notice renders under the affordance: *“The previous
waiver was cleared because the capability changed — write a new one for this capability if it should still run
un-gated.”* A justification is never carried onto a different capability.

## 3. The review summary — before / after (D3)

`gatesOf` (`humanize.ts`) filtered `hitl_mode !== "none"`, so a side-effectful step running with **no** gate under
a waiver — the single highest-risk item — vanished from the summary. Now `gatesOf` keeps any binding with a
`side_effect_waiver`, tags it `waived` + carries the `justification`, and the surfaces render it as a distinct
danger row, sorted first:

- **CopilotReview** (“Where a person is involved”): a red banner *“N steps act on the real world with no one
  approving”*, then each waived step as a bordered danger row (`data-testid="waived-gate"`) with a **“no approval —
  waived”** badge and the quoted justification.
- **CopilotSteppedReview / Understanding**: the same danger row inline among the human-involvement rows.
- The wizard's own Bindings step shows the live `WaiverAffordance` (the waived state IS the loud row there).

A reader skimming the review can now answer “what does this process do without asking me?” without expanding
anything — the waived steps are the first, reddest rows.

## 4. Pack detail (D4)

`PackDetailPage` overview now: (a) each waived binding's HITL cell shows a **“waived — no approval”** danger badge
instead of a bare “none”; (b) a dedicated **“Side-effect waivers (N)”** card lists element + capability +
justification for every waived binding. Visible to any authenticated viewer (transparency for a non-owner
auditor); creating/editing stays owner-gated by the existing Edit-config flow — no new authorization surface.

## 5. The copilot-review path and the guard interaction (D5)

The copilot review sets a waiver through the **same `BindingsStep`** (no LLM involvement): no mutation kind, no
proposal field, no copy inviting the model to suggest one — the operator writes it, the model cannot (ADR-065 Part
C). Persisting goes through `setOnboardingBindings` → `session.bindings`, exactly the state the copilot guard reads.
The survive/drop guard is backend behavior (`reconcile.py::_waiver_drop_reason`) and is covered by the existing
tests `test_copilot_chat_preserves_operator_waiver` (survives an unrelated turn),
`test_copilot_chat_drops_waiver_on_rebind`, and `test_copilot_chat_drops_waiver_on_explicit_gate_raise` — each sets
the waiver on `session.bindings` (the path the affordance writes) then runs a chat turn. The new webui test
`waiver.test.tsx` proves the affordance writes `side_effect_waiver` into that PUT `/bindings` payload, closing the
webui→guard chain.

## 6. Deliverable 6 — the backend string

`pack_validator.py`'s `side_effect_waived` warning said *“runs a side-effectful capability WITHOUT a human gate”* —
false for the assist case (there IS a gate; the assist precedes it). Reworded (no logic change) to be accurate for
both: *“'<el>' performs a real-world (side-effectful) action with no human approval before it takes effect
(hitl '<mode>'), under an explicit waiver. Justification: …”*.

## 7. Verification

| Check | Result |
|---|---|
| `tsc --noEmit` / `npm run build` | **green** (2166 modules) |
| `vitest run` | **210 passed** (30 files); +8 new (`waiver.test.tsx` ×5, copilot D3 ×1, and the a11y-labeled selects keep the existing copilot suite green) |
| process-registry `pytest` | **422 passed** (only P3 change is D6's string; the `side_effect_waived` test still passes — justification still in the message) |
| agent-runtime `pytest` | **exit 0**, and **untouched by P3** (its working-tree changes are all P2's; P3 edited only webui + `pack_validator.py`) |
| OpenAPI / generated types | **no P3 change** — `side_effect_waiver` was already generated in P1; nothing re-dumped or regenerated |

**The emphasized assertion (waived step is _present_, not merely un-crashed):**
`copilot.test.tsx` → *“a WAIVED step is surfaced as a loud risk row on Understanding — not silently dropped”* seeds
a `hitl_mode: "none"` binding with a `side_effect_waiver` and asserts the row text (*“Fire ticket runs
automatically, with no one approving it.”*), the **“no approval — waived”** badge, and the justification are all
`toBeInTheDocument()` — a test that only rendered the page would have passed against the pre-P3 bug, so it asserts
presence, not absence-of-crash.

Other asserted acceptance: `none` is disabled on a side-effectful row until a ≥20-char justification exists, then
selectable; setting the waiver drops the gate to `none` and the PUT payload carries `side_effect_waiver`; changing
the capability drops the waiver and shows the notice; the affordance rejects <20 chars and has no toggle.

## 8. For P4 — the Playwright journey this phase did not add

A journey to add alongside the P4 fixture migration:
1. Onboard a pack whose one side-effectful step is left at the floor → wizard blocks `none`; write a ≥20-char
   justification → `none` unlocks; assemble → validation clean with a `side_effect_waived` warning; go live.
2. Open the pack detail as a **non-owner** → the “Side-effect waivers” card is visible; no edit control.
3. Re-open the pack for edit, rebind that step to a different capability → assert the waiver-cleared notice and
   that go-live now requires a fresh justification.
4. In the copilot flow, set a waiver in the Bindings step, send an unrelated chat turn → waiver survives; send a
   rebind turn → waiver dropped (mirrors the backend guard end-to-end through the real UI).
