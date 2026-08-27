# Claude Code prompt — collapse the e2e into ONE copilot-driven ACH lifecycle test (retains everything; delete all the flag/deterministic/throwaway clutter)

Replace the whole flag-riddled e2e suite with **one** simple, realistic test: the copilot (real LLM) onboards the
three ACH segments, roles are assigned from the onboarded packs, the cohort + DAG + SLA are created, and the three
pega-stub scenarios run — then **everything is retained** (no teardown) so it never has to be redone by hand.
**Delete the deterministic onboarding, the `e2e-copilot-*` throwaway journey, and every `--copilot`/`--keep`/
`--keep-copilot` / `E2E_*` flag.** Source of truth for the use case:
`backend/docs/methodology/worked-examples/ach_exposure` (BPMN, schemas, cohort close schema, ONBOARDING.md).

## Why
The deterministic onboarding won't be used in prod, and the flags + the misleading single `e2e-copilot-*` pack are
clutter. Prod onboarding is the **copilot**. We want ONE end-to-end test that mirrors real usage and leaves a live,
inspectable ACH cohort behind.

## The single test — `e2e/tests/ach-lifecycle.spec.ts` (rewrite as the ONLY spec)
Run as **priya** for onboarding/cohort authoring; drive gates as the role-holders. All three segments onboarded by
the **copilot autopilot through the UI** (accept-as-is, stable outcomes only — never assert LLM-inferred values).

1. **Copilot-onboard the 3 segments (real LLM, well-named packs).** For each segment, drive `/registry/onboard`
   (the copilot front door) as priya: upload the BPMN, point at the segment's MCP server, author the trigger
   schema + triage rule (from the worked example), **Generate → accept the draft as-is → publish**. Inputs per
   segment (from ONBOARDING.md §1):
   | Segment | BPMN | MCP | trigger schema (`schemas/`) | triage `request_type` |
   |---|---|---|---|---|
   | Assess  | `ach-exposure-assess.bpmn`  | `http://ach-assess-mcp:8075/mcp`   | `art.ach.assess_exposure_requested.json`  | `AssessExposureRequested` |
   | Enforce | `ach-decision-enforce.bpmn` | `http://ach-enforce-mcp:8076/mcp`   | `art.ach.enforce_decision_requested.json` | `EnforceDecisionRequested` |
   | Closeout| `ach-closeout.bpmn`         | `http://ach-closeout-mcp:8077/mcp`  | `art.ach.closeout_requested.json`         | `CloseoutRequested` |
   - **Let the copilot name each pack** (it infers a good name). **Capture the published `pack_key` per segment**
     (from the success/registry) and keep the segment→pack_key map (you know which BPMN produced which).
   - Assert each publishes clean + is **active** in `GET /packs` (stable outcome only). Requires the copilot model
     (`dev.llm.bedrock.explicit-creds`); if `copilot/generate` → `502 copilot_llm_unavailable`, **skip** the whole
     test with a clear message (copilot-only by design).
   - **Set cohort membership on each pack** (the copilot won't — it's not in the BPMN):
     `PUT /packs/{captured_pack_key}/1.0.0/cohort-membership {cohort_def_id: "ach_exposure_cohort",
     correlation_key: "case_id"}`.

2. **Assign roles from the onboarded packs (post-onboard, no service restarts).** Read each published pack's
   HITL/gate roles (`GET /packs/{key}` → the bindings' `hitl_role`s / `policies`). Grant them so the **enforce
   approver ≠ the assess/closeout reviewer** (SoD via role split): enforce role → **Marcus**, assess + closeout
   roles → **Riya**; **priya** only onboards/owns. Grant via the identity pending-stage/admin path **after**
   onboarding (base roles are seeded; only the `ach_*` roles are added). Do **not** restart identity/config-forge/
   notification (or any service) anywhere.

3. **Create the cohort with the right members + DAG + SLA (as priya).** `POST /cohort/definitions`
   `cohort_def_id: ach_exposure_cohort`, close schema/correlation/outcome paths from
   `schemas/cohort.ach_exposure.close.schema.json`, and the expectation graph over the **captured pack_keys**:
   `__start__ → assess → enforce → closeout → __close__` (all `expected`/`and`), with the **enforce→closeout
   arrival SLA** tuned to the pega breach scenario — `deadline 8s, at_risk 4s, wall, owner external` (8s so
   `late_closeout`'s ~25s delay deterministically breaches while the immediate flows satisfy). Assert the
   definition shows **Members 3** (the three packs) and the DAG/SLA read-back.

4. **Run the 3 pega-stub scenarios and drive them.** Fire via `pega_stub` `POST /cases`; drive each segment's gates
   through the Task Inbox as the role-holder (assess handback-approval → Riya; enforce decision+actions → Marcus;
   closeout review+actions → Riya). Assert per flow the **cohort reaches MEMBERS = 3 (all joined & terminal) and
   closes** — a 1-member stall fails:
   - `credit_approve` → 3 members, **Released**.
   - `debit_reject` → 3 members, **Purged**.
   - `late_closeout` → enforce→closeout SLA **breached (external)**, closeout arrives late, closes **Released**, 3 members.

5. **Retain everything — NO teardown.** The test leaves the 3 packs, the cohort definition + its instances/runs,
   and the granted roles in place, so priya can inspect the live cohort afterwards. (Re-running requires a clean DB —
   document that; on a dirty stack the test may 409 on create, which is fine/expected. Optionally skip-with-message
   if the packs already exist.)

## Delete the clutter
- **Flags/env:** remove `--copilot`, `--keep`, `--keep-copilot`, and `E2E_COPILOT`/`E2E_KEEP`/`E2E_KEEP_COPILOT`
  from `tools/e2e.sh` and `e2e/support/env.ts`. `tools/e2e.sh` becomes a **single command**, no args:
  `bash tools/e2e.sh` runs the one test and retains everything.
- **Deterministic onboarding:** delete `e2e/fixtures/onboarding/onboard_ach.py` and its deterministic setup path
  (`ensureAchDomain`/`global-setup` deterministic onboarding). Keep only what the single test needs (persona login /
  storageState, pega/stub drivers, the gate-driving + role helpers, the cohort/SLA + registry helpers).
- **Throwaway copilot spec:** delete `e2e/tests/copilot-onboarding.spec.ts` (the `e2e-copilot-*` pack) — its purpose
  is now the real ACH onboarding.
- **Other feature specs:** remove the now-redundant `e2e/tests/{onboarding,onboarding-condition,cohorts,
  dag-sla-editor,hitl-arc,owner-gating,live-sse,instance-diagram,_smoke}.spec.ts`. **Fold the still-valuable
  orthogonal checks into the one test** as inline assertions where they occur naturally — specifically: **owner-gating**
  (a non-owner, e.g. marcus, does NOT see the Registry/onboarding surface), the **condition-normalization** behaviour
  if a segment's BPMN carries a Camunda `${…}` gateway, and a **live-SSE** check (a fired case's cohort/instance row
  updates without reload). Don't create separate spec files for them.
- Update `e2e/README.md` + `backend/docs/engineering/running-e2e-tests.md`: one command, copilot-driven, retains
  everything, needs the copilot model + `mcp_stub` + `pega_stub`, re-run after a DB wipe.

## Do not
- Do not keep any deterministic/`--flag` path or the `e2e-copilot-*` throwaway. Do not assert LLM-inferred values —
  stable outcomes only (published/active, Members 3, 3-joined-and-closed, SLA breach). Do not restart any service
  from the test. Do not tear anything down. No fixed sleeps (auto-wait/`expect.poll`; long waits for LLM/pega). No git writes.

## Acceptance
- On a clean stack (services up incl. the three ACH MCP servers + pega_stub + the copilot model), **`bash tools/e2e.sh`**
  (no flags) runs the **one** test green: the copilot onboards **3 well-named ACH packs** (active), roles are granted
  from the packs (enforce→Marcus, assess/closeout→Riya, priya owns), the **ach_exposure_cohort** shows **Members 3** +
  the DAG + the enforce→closeout SLA, and `credit_approve`/`debit_reject`/`late_closeout` each drive the cohort to
  **3 members / closed** (Released / Purged / external-breach→Released). **Nothing is torn down** — the packs, cohort,
  instances, and roles remain for inspection.
- No `--copilot`/`--keep*` flags or `E2E_*` env or `onboard_ach.py` remain in the tree; `tools/e2e.sh` takes no args.
- If the copilot model is unavailable, the test **skips** with a clear message (copilot-only by design).

## Final step — report
`backend/docs/_build-reports/claude_code_prompt_ach_copilot_single_test_report.md` (uncommitted): (1) outcome; (2)
the single-test flow (copilot onboarding of the 3 segments incl. the captured pack names, cohort-membership set,
role split, cohort+DAG+SLA, the 3 pega flows) + the folded-in orthogonal checks; (3) exactly what was **deleted**
(flags, env, `onboard_ach.py`, the throwaway + feature specs); (4) verification — a green `bash tools/e2e.sh` from a
clean stack with the 3 packs + 3-member cohort **retained** afterwards (paste the run); (5) the re-run-needs-wipe
note; (6) any copilot-shape wrinkle handled. One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `e2e/` + `tools/e2e.sh` + docs only (delete
`onboard_ach.py` + the redundant specs). One simple test, copilot-onboarded 3 ACH segments, roles from the packs,
cohort+DAG+SLA, three pega flows, **retain everything**, zero flags. Copilot-only; stable outcomes; no service
restarts; no teardown.
