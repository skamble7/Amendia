# Copilot journey — fix accept-as-is navigation + keep the generated pack

**Outcome:** the copilot/LLM journey now drives the stepped review **through publish and greens** (verified: 1 passed,
37s draft), asserting the `e2e-copilot-*` pack registers **active** — no inferred-value assertions. New `--keep-copilot`
leaves just the generated pack for inspection while the ACH stack still tears down. Only `e2e/` + `onboard_ach.py` +
`tools/e2e.sh` + docs changed. No git writes.

## 1. Fixed the accept-as-is navigation (the Continue timeout)
**Real stepper** (`CopilotSteppedReview`): 7 steps — Understanding · Capabilities · Artifacts & schemas · Bindings ·
Trigger & triage · Gateways · Review & go live. Read-mostly steps advance via a shared **"Continue"**; the **persist
steps** (Bindings/Gateways) run a **server-side assemble** on Continue and **disable** the button while `busy`; the
final step has **no Continue** — `CopilotReview` shows **"Ready to go live"** / **"Not ready to go live yet"** + the
**"Approve & go live"** publish button. The trace showed the old loop's `cont.click()` timing out at 20s — a blind
click into that disabled/assembling window.

**New walk** (`e2e/tests/copilot-onboarding.spec.ts`) is **enable-aware + settle-aware**, no fixed sleeps:
- loop until the **publish button** is visible; each iteration first `await expect(Continue).toBeEnabled()` (waits out
  the assembling/`busy` window so it never clicks a disabled button), clicks, then **settles** via `expect(...).toPass`
  that polls until *either* the publish button appears *or* the next step's Continue is enabled again (the persist-step
  assemble completes before the next step renders). This transition-aware settle is what removes the timeout.
- **Readiness gate:** "Not ready to go live yet" → **fail** with the surfaced readiness/open-questions reason (a real
  copilot-quality signal); "Ready to go live" → click "Approve & go live".
- **Publish assertion = model-agnostic:** dropped the guessed success-heading; the proof is STABLE OUTCOME 3 —
  `expect.poll(activePackKeys().has(packKey))` (the pack registers **active** in `GET /packs`), generous 60s timeout
  (commit is a server round-trip). The 502-skip vs hard-error gate before the walk is unchanged.

## 2. Green `--copilot` run (through publish)
```
RUN A (E2E_COPILOT=1):  ✓ copilot-onboarding … "draft publishes clean into a registered pack" (37.1s)  → 1 passed
                        teardown: removed copilot throwaway pack e2e-copilot-1786746230694
Full default suite:     15 tests → 13 ✓, 2 skipped (copilot #4 skipped, no LLM; cohorts:28 pre-existing cold-stack) → green
```

## 3. `--keep-copilot` / `E2E_KEEP_COPILOT`
Granular keep: `KEEP_COPILOT` in `e2e/support/env.ts`; `--keep-copilot` in `tools/e2e.sh` (sets `E2E_KEEP_COPILOT=1` +
banner); `onboard_ach.py --teardown` reads it (via the driver env) and **skips `_delete_copilot_packs()`** while still
revoking roles + deleting the cohort def + ACH packs. Precedence `E2E_KEEP` ⊇ `E2E_KEEP_COPILOT` (full `--keep`
short-circuits the driver teardown entirely). Verified:
```
RUN B (E2E_COPILOT=1 E2E_KEEP_COPILOT=1):  ✓ 1 passed (39.7s)
   teardown: keeping copilot throwaway pack(s) (E2E_KEEP_COPILOT set) · removed cohort definition + ACH packs
   after → e2e-copilot-1786746293308 KEPT; ACH packs (none — torn down)
   next non-keep run → "teardown: removed copilot throwaway pack e2e-copilot-1786746293308" (prefix-sweep clears it)
```
`--keep` still keeps everything; default (no flag) unchanged (copilot skipped, no LLM, existing journeys green).

## 4. Follow-ups / notes
- **Stack repair (not a code change):** on arrival the stack was wedged — all personas had **empty roles** (the
  identity `role_assignments` collection was empty, from the ~20-min-ago identity/config-forge restart when the copilot
  model was provisioned). The seed only stages **unprovisioned** emails, so a restart wouldn't restore already-
  provisioned personas, and `down -v` would wipe the operator's just-provisioned copilot cred (stored in the separate
  `ConfigForge` Mongo DB → back to 502). I restored the three personas' seed `role_assignments` directly in Mongo
  (non-destructive, ConfigForge preserved) to unblock verification. If personas go roleless again, that's the identity
  seed's provisioned-skip behavior, not this journey.
- No changes to `webui/src`, `backend/tests/smoke`, or the deterministic execution journeys — build/vitest/smoke
  untouched by construction.
- The copilot draft on this stack is genuinely **publishable** (readiness clean) — the journey greens end-to-end; if a
  future model/prompt regresses draft quality it will fail with the readiness reason, not a selector timeout.
