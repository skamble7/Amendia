# e2e — opt-in copilot (LLM) onboarding journey (accept-as-is, stable outcomes only)

**Outcome:** added an **opt-in** Playwright journey that drives the **real copilot autopilot** end-to-end (upload →
LLM draft → accept as-is → publish) and asserts **stable outcomes only**. Default suite is unchanged (LLM-free, fast).
Verified: default run **skips** it (no LLM); a `--copilot` run on this stack (no model provisioned) drives the full
autopilot and **skips cleanly on the real 502**. Only `e2e/` + `tools/e2e.sh` + `onboard_ach.py` + docs changed. No
git writes.

## 1. The flag + how the journey drives the autopilot
- **Flag:** `COPILOT_ENABLED` in `e2e/support/env.ts` (`E2E_COPILOT` truthy), mirroring `E2E_KEEP`. `tools/e2e.sh
  --copilot` sets `E2E_COPILOT=1` and prints a banner ("copilot LLM journey enabled — slower, needs model creds").
  Default off → `test.skip(!COPILOT_ENABLED, …)` short-circuits before any LLM contact.
- **Journey** (`e2e/tests/copilot-onboarding.spec.ts`, as **priya**): the copilot front door `/registry/onboard`
  (`CopilotFlow` → `CopilotStart`) — upload the ACH **assess** BPMN, point at the live **ach-assess-mcp** (a coherent
  pairing the deterministic driver already publishes clean), supply the USER-PROVIDED trigger (a sample
  `AssessExposureRequested` event) + one triage rule (`request_type == …`), then **Generate process** (one live LLM
  call). It waits on real signals with a long timeout (no fixed sleep), steps the review **without editing** (clicks
  "Continue" through all steps — accept-as-is), and clicks **"Approve & go live"**.
- **Stable outcomes asserted:** (1) a draft came back and stepped to **"Review your process"**; (2) it is
  **publishable** ("Ready to go live"); (3) after publish, **"Your process is live"** and the pack **registers active**
  in `GET /packs` (`activePackKeys`). It asserts **no** LLM-inferred value (bindings/HITL/gateways/triage).

## 2. Skip (no model) vs. failure (unpublishable draft)
- **No model → skip:** after Generate, the journey waits for the review heading **OR** the wizard's 502 surface
  ("…isn't reachable right now") **OR** a generic generate error. On the 502 surface →
  `test.skip("copilot LLM not configured on this stack (502 copilot_llm_unavailable)")` — never a red.
- **Draft-but-unpublishable → failure:** if the review shows **"Not ready to go live yet"**, the test **throws** with
  the readiness/open-questions reason (a real product regression, not an environment gap). A generic generate error
  (non-502, e.g. MCP unreachable) also fails fast with its message — distinct from the model-availability skip.

## 3. Throwaway pack + teardown
The pack uses a distinct `e2e-copilot-<timestamp>` key — never fed to the execution journeys (those keep the
deterministic ACH setup). `onboard_ach.py` teardown gained `_delete_copilot_packs()`: it lists active packs and
clean-deletes any `e2e-copilot*` (by **prefix**, so a crashed prior run's leftover is swept too — the runtime key
isn't known to teardown). Runs under the existing `--teardown` path, so it's skipped under `E2E_KEEP` like the rest,
and is a no-op when nothing published.

## 4. Verification (live stack)
- **Default `bash tools/e2e.sh` (no flag):** copilot spec **1 skipped**, **zero** LLM/generate activity in the log —
  unchanged speed.
- **`E2E_COPILOT=1` on this stack:** the journey drove the full autopilot input flow — the registry received
  `POST /onboarding/copilot/generate` (proving upload + MCP + trigger + triage + Generate all executed) — and
  ConfigForge returned **404** for `dev.llm.bedrock.explicit-creds` → the endpoint returned **502
  copilot_llm_unavailable** → the journey **skipped cleanly** ("copilot LLM not configured"), **EXIT 0**, no red. No
  `e2e-copilot*` pack lingered.
- **Latency:** on this stack the 502 returned **fast** (it fails at ConfigForge cred resolution, before any model
  round-trip), so the skip is quick. A stack **with** resolvable creds would incur the real generate latency (tens of
  seconds — the journey allows up to 180s for the draft).
- **Untouched:** no changes to `webui/src`, `backend/tests/smoke`, or the deterministic execution journeys — webui
  build/vitest and pytest smoke are unaffected by construction.

## 5. Note / follow-up
The **publish-clean happy path** (draft → "Your process is live" → registered) could not be exercised here because
this dev stack has **no provisioned copilot model** (`dev.llm.bedrock.explicit-creds` is a 404 in ConfigForge). The
journey's happy-path logic is in place and its entire **input** path is proven (the generate call fired); to green the
publish assertions, run `--copilot` on a stack with real Bedrock creds resolvable in ConfigForge (or a configured
`COPILOT_LLM_CONFIG_REF`). No code change needed — it's an environment prerequisite.
