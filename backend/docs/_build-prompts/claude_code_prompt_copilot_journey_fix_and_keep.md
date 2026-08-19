# Claude Code prompt — fix the copilot journey's accept-as-is navigation + keep the generated pack (config)

The opt-in copilot journey now reaches the LLM (model resolves; draft returns in ~37s and steps into review), but
fails driving the **stepped review** to publish, and the operator wants the **generated pack to persist** for
inspection. Two fixes. No git writes.

## 1. Fix the accept-as-is step navigation (`e2e/tests/copilot-onboarding.spec.ts`)

**Failure:** the loop `click Continue ×10 until "Approve & go live"` times out on `cont.click()` — the naive loop
doesn't match the real copilot stepper.

**The real structure** (read `webui/src/features/copilot/CopilotSteppedReview.tsx` + `CopilotReview.tsx` +
`CopilotFlow.tsx`, and open this run's trace `e2e/.artifacts/copilot-onboarding-*/trace.zip` to see where it stuck):
- A **7-step** stepper: `Understanding, Capabilities, Artifacts & schemas, Bindings, Trigger & triage, Gateways,
  Review & go live`. Read-mostly steps advance via a shared `StepFooter` **"Continue"** (`onNext → setStep+1`).
- **Persist steps** (e.g. bindings/artifacts) run a **server-side assemble** on Continue and toggle a `busy` state
  → the Continue button is **disabled while assembling**, and state can briefly regress (see the file's own comment
  about "a persist step's Continue already ran its own setter (regressing state); re-drive the tail back to
  ASSEMBLED"). A blind `.click()` races that disabled/re-rendering window → the timeout you saw.
- The **final step** (`Review & go live` → `CopilotReview`) has **no Continue** — it shows **"Ready to go live"** /
  **"Not ready to go live yet"** and the publish button labelled **"Approve & go live"** (new pack) — then a
  post-publish success state (`Published <pack> …`).

**Rewrite the accept-as-is walk to be stepper-aware and settle-aware:**
- Advance by detecting **step change** (the active step label/heading, or the step index) — not merely "a Continue
  is visible". Before each Continue click, **wait for it to be enabled** (`toBeEnabled`) so you never click through
  the `busy`/assembling window; after the click, **wait for the next step to settle** (next step's heading, or the
  Continue re-enabled, or the `Review & go live` step). Loop until the `Review & go live` step is active.
- On the review step: if **"Not ready to go live yet"** → **fail** with the readiness/open-questions reason
  (genuine copilot-quality signal, per design). If **"Ready to go live"** → click **"Approve & go live"**.
- **Publish assertion — prefer the model-agnostic one:** the robust proof is STABLE OUTCOME 3 (the pack appears
  **active** in `GET /packs` via the existing `expect.poll` on `activePackKeys()`). Replace/loosen any guessed
  success-heading text (e.g. "Your process is live") with the **actual** post-publish indicator (the `Published …`
  state in `CopilotReview`) **or** just rely on the `GET /packs` poll. Keep the timeout generous (assemble +
  publish are server round-trips).
- Keep the skip-vs-fail gate before this (502 "isn't reachable" → skip; hard error → fail) unchanged.
- No fixed sleeps — wait on real signals (`toBeEnabled`, heading/step transitions, `expect.poll`).

**Verify green now:** the model resolves on this stack, so a `bash tools/e2e.sh --copilot` run must now drive the
autopilot **through publish** and green the journey (or, if the LLM draft is genuinely not publishable, fail with
the surfaced readiness reason — not a selector timeout).

## 2. Keep the generated pack for inspection (config)

Today `--keep` (skip **all** teardown) already persists everything, incl. the copilot pack —
`bash tools/e2e.sh --keep --copilot`. Add a **granular** option so the operator can keep **just the LLM-generated
pack** while the ephemeral ACH stack still tears down:
- **`E2E_KEEP_COPILOT`** (env, via `e2e/support/env.ts`) + **`--keep-copilot`** in `tools/e2e.sh` (mirror
  `--keep`/`--copilot` arg-parse + a banner). When set, `onboard_ach.py --teardown` **skips `_delete_copilot_packs()`**
  (leaves the `e2e-copilot-*` pack in the registry) but still revokes roles + deletes the cohort def + ACH packs.
- Precedence: `E2E_KEEP` (keep everything) ⊇ `E2E_KEEP_COPILOT` (keep only the copilot pack). Both default off →
  today's full teardown.
- Note the accumulation trade-off in the docs: with `--keep-copilot`, each copilot run leaves one
  `e2e-copilot-<ts>` pack; the **next non-keep run's** `_delete_copilot_packs()` prefix-sweep clears old ones (it
  already sweeps by prefix), or `down -v`.
- Document `--keep-copilot` / `E2E_KEEP_COPILOT` alongside `--keep` and `--copilot` in
  `backend/docs/engineering/running-e2e-tests.md` + `e2e/README.md`.

## Do not
- Do not assert LLM-inferred values (bindings/HITL/gateways/triage) — stable outcomes only (draft → review reached
  → publishable → pack registered). Do not re-enable the journey by default. Do not touch the deterministic ACH
  setup/execution journeys. No fixed sleeps. No git writes.

## Acceptance
- `bash tools/e2e.sh --copilot` (model present, as now): the copilot journey **drives the stepped review to
  publish and greens**, asserting the `e2e-copilot-*` pack is **active** in `GET /packs` (no inferred-value
  assertions). A genuinely unpublishable draft fails with the readiness reason (not a Continue timeout).
- `bash tools/e2e.sh --copilot --keep-copilot`: journey green **and** the `e2e-copilot-*` pack **remains** in the
  registry after the run (visible in `GET /packs` / the Registry UI), while ACH packs + cohort def are torn down.
  `--keep` still keeps everything.
- Default `tools/e2e.sh` unchanged (copilot skipped, no LLM). Existing journeys + pytest smoke + webui build/vitest
  untouched.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_copilot_journey_fix_and_keep_report.md` (uncommitted):
(1) outcome one-liner; (2) the real stepper structure + how the new accept-as-is walk is persist-step/settle-aware
(what fixed the Continue timeout) + the publish assertion actually used; (3) the green `--copilot` run (through
publish) — paste the per-journey result; (4) `--keep-copilot` / `E2E_KEEP_COPILOT` (what it preserves vs `--keep`)
+ a run proving the pack persists; (5) follow-ups. One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `e2e/` + `onboard_ach.py` + `tools/e2e.sh` + docs only;
reuse the real `CopilotSteppedReview`/`CopilotReview` labels (verified from the components + the trace), the
`E2E_KEEP` flag pattern, and the prefix-sweep teardown. Stable-outcomes-only; green the copilot journey through
publish on a model-present stack; keep the generated pack when asked.
