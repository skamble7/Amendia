# Claude Code prompt — e2e: **opt-in copilot (LLM) onboarding journey** (accept-as-is, stable outcomes only)

The e2e suite currently exercises only the **deterministic/technical** onboarding path (`infer_draft`, no LLM) —
fast and reproducible, but it never touches the **copilot/LLM autopilot** a real user uses. Add an **opt-in**
journey that drives the real copilot end-to-end: upload → LLM generates a draft → **accept it as-is** → publish →
assert it **completed into a valid, published pack**. We do **not** validate what the LLM inferred — only that
onboarding *completes cleanly*. Gated by a config flag so the default suite stays fast, LLM-free, and deterministic.

## Design (Sandeep's, confirmed against the code)
- **Opt-in flag** `E2E_COPILOT` (like `E2E_KEEP`): default **off** → the copilot journey is skipped and nothing
  changes. On → the journey runs.
- **Accept-as-is:** `copilot/generate` is designed to return a **validator-clean draft** (its docstring), so driving
  the wizard's copilot autopilot and accepting the proposal through review → **commit/publish** genuinely completes.
- **Stable outcomes only:** assert a draft was produced (bindings populated), it **passes validation**, and the pack
  **registers** in `GET /packs`. **Never** assert inferred binding/HITL/gateway values (non-deterministic).
- **Skip when no model:** `copilot/generate` returns **`502 copilot_llm_unavailable`** when the LLM isn't
  configured (or `COPILOT_LLM_DISABLED=true`) → the journey **skips with a clear message**, never a red.
- **Separate from execution setup:** do **not** replace the deterministic `onboard_ach.py` — it keeps feeding the
  HITL/cohort/SSE journeys reliably. The copilot pack is a **throwaway**, clean-deleted in teardown.

## Read first
- `backend/services/process-registry/app/routers/onboarding.py` — `POST /onboarding/copilot/generate`
  (autopilot → validator-clean draft + `copilot_report` incl. open questions) and `502 copilot_llm_unavailable`
  on `CopilotLLMError`; the stepped review + `commit` that publishes.
- `backend/services/process-registry/app/config.py` — `COPILOT_LLM_CONFIG_REF`, `COPILOT_LLM_DISABLED` (how the
  stack signals the model is present/absent — drives the skip).
- `webui/src/features/registry/OnboardingWizard.tsx` — the **"Refine with the copilot"** panel / autopilot entry in
  the wizard (the UI the journey drives), the review steps, and Publish.
- `e2e/tests/onboarding.spec.ts` (the deterministic wizard journey to mirror the structure/selectors of),
  `e2e/support/env.ts` (add the flag), `e2e/support/setup.ts` + `fixtures/onboarding/onboard_ach.py` (teardown to
  extend for the throwaway pack), `tools/e2e.sh` (add `--copilot`).

## Deliverables

### 1. The flag (`E2E_COPILOT` / `--copilot`)
- Read `COPILOT_ENABLED` from `e2e/support/env.ts` (`E2E_COPILOT` truthy). Add `--copilot` to `tools/e2e.sh` (sets
  `E2E_COPILOT=1`, banner "copilot LLM journey enabled — slower, needs model creds"). Default off.

### 2. The copilot journey (`e2e/tests/copilot-onboarding.spec.ts`, opt-in)
- `test.skip(!COPILOT_ENABLED, "set E2E_COPILOT=1 to run the copilot/LLM onboarding journey")` at the top.
- As **priya**: open the technical wizard, upload the Camunda `${…}` BPMN (`fixtures/camunda-gateways.bpmn` or a
  richer representative BPMN), invoke the **copilot autopilot** ("Refine with the copilot" / generate). **Wait for
  the LLM draft with a long timeout** (e.g. 120s — real model latency; use `expect.poll`/`waitFor`, no fixed sleep).
- **Accept as-is:** step through the review **without editing** the inferred values, to **Publish**.
- **Assert stable outcomes:** the draft came back with bindings populated (session progressed), the review/validation
  is clean, and after Publish the pack is **registered** (`GET /packs`, status active) with a **distinct throwaway
  `pack_key`/version** (so it never collides with the ACH execution packs). **Do not** assert any inferred value.
- **LLM-unavailable → skip, not fail:** if the copilot call surfaces `copilot_llm_unavailable` (the wizard shows the
  502 / a "copilot unavailable" state), `test.skip(true, "copilot LLM not configured on this stack")`. Distinguish
  this cleanly from a genuine "draft produced but won't publish" (that's a real **failure** — surface the validation/
  open-questions reason).

### 3. Teardown (throwaway pack)
- Clean-delete the copilot-published pack (ADR-061) in teardown — reuse `onboard_ach.py`'s delete or add a small
  step. Idempotent; skipped under `E2E_KEEP` like the rest.

### 4. Docs (`backend/docs/engineering/running-e2e-tests.md` + `e2e/README.md`)
- Document `--copilot` / `E2E_COPILOT`: it exercises the **real LLM** autopilot (slow, **costs model calls**),
  **accepts the inference as-is** and only asserts the pack published clean, **skips** when the stack has no copilot
  model, and is meant for **manual / nightly** runs — not the fast default suite. Note it does not replace the
  deterministic onboarding used for the execution journeys.

## Do not
- Do not enable it by default; the standard `tools/e2e.sh` stays LLM-free/fast/deterministic.
- Do not assert LLM-inferred values (bindings/HITL/gateways/triage). Do not feed the copilot pack into the
  execution journeys — keep the deterministic ACH setup as the execution source.
- Do not treat "model not configured" as a failure (skip). No fixed sleeps (long `expect.poll`/`waitFor`). No git
  writes.

## Acceptance
- **Default** `bash tools/e2e.sh` (no flag): unchanged — copilot journey **skipped**, no LLM contacted, same speed.
- `bash tools/e2e.sh --copilot` on a stack **with** copilot model creds: the journey drives the autopilot, waits out
  the LLM, accepts the draft as-is, **publishes**, and asserts the pack is registered + validation-clean
  (no inferred-value assertions); teardown clean-deletes it (unless `--keep`).
- `--copilot` on a stack **without** the model (or `COPILOT_LLM_DISABLED=true`): the journey **skips** with a clear
  message — never a red.
- No change to the deterministic execution journeys; existing pytest smoke + webui build/vitest untouched.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_copilot_onboarding_e2e_report.md` (uncommitted): (1) outcome
one-liner; (2) the flag + how the journey drives the copilot autopilot and what **stable outcomes** it asserts;
(3) the LLM-unavailable **skip** path vs the unpublishable-draft **failure** path; (4) the throwaway pack + teardown;
(5) verification — default run skips it (fast, no LLM), a `--copilot` run **with** creds publishes clean, a run
**without** creds skips; note the real LLM latency observed. One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `e2e/` + `tools/e2e.sh` + docs only; reuse the wizard
selectors, the `E2E_KEEP`-style flag pattern, and the ADR-061 teardown. Opt-in, accept-as-is, stable-outcomes-only,
skip-when-no-model, separate from the deterministic execution setup.
