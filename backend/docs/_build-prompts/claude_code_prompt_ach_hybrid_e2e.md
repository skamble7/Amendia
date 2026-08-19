# Claude Code prompt — HYBRID ACH e2e: keep the deterministic gate, add a defensive copilot lifecycle spec, strip the flag clutter

Decision (Sandeep, after CC's de-risk — see `backend/docs/_build-reports/ach_copilot_derisk_findings.md`): **hybrid.**
Keep the deterministic suite as the reliable CI gate; add a **separate, defensive, skip-on-502 copilot lifecycle
spec** that onboards the 3 ACH segments via the **real LLM** and **retains a live cohort** for inspection; and
**remove the confusing flag maze** (`--copilot`/`--keep`/`--keep-copilot`, `E2E_COPILOT`/`E2E_KEEP`/
`E2E_KEEP_COPILOT`). Two clean commands, no flags. Source of truth for the use case:
`backend/docs/methodology/worked-examples/ach_exposure`.

## Why hybrid
The deterministic suite tests the **runtime** (cohort formation, membership, gates, SLA breach, pega A→B→C) — which
IS prod — with a fast, reliable onboarding fixture, so it's the CI gate. The copilot spec tests the **onboarding
path** as prod does it (LLM inference → pack). Per the de-risk report, a pure-copilot gate is flaky (inferred
schemas vary per run, inference variance, read-after-write, non-evicting bundle-cache), so the copilot spec is
**non-blocking**: its own command, skips when the model is absent, and never gates CI.

## Deliverables

### 1. Deterministic suite = the CI gate (keep coverage; remove flags only)
- Keep the existing deterministic specs + `onboard_ach.py` + global-setup/teardown **intact** (the faithful ACH
  lifecycle already landed: side-effect gating on all 3 segments, Members-3, DAG+SLA, the 3 pega flows). This stays
  green and tears down as today.
- **Remove the flag machinery:** delete `--copilot`/`--keep`/`--keep-copilot` from `tools/e2e.sh` and the
  `E2E_COPILOT`/`E2E_KEEP`/`E2E_KEEP_COPILOT` reads in `e2e/support/env.ts`. `bash tools/e2e.sh` (no args) runs the
  deterministic gate and **excludes** the copilot spec (Playwright project/`testIgnore` or a `@copilot` grep).
- **Delete the throwaway** `e2e/tests/copilot-onboarding.spec.ts` (the misleading `e2e-copilot-*` single pack) — its
  purpose is superseded by the real copilot lifecycle spec below.

### 2. New copilot lifecycle spec — `e2e/tests/ach-copilot-lifecycle.spec.ts` (defensive, retains, skippable)
Self-contained (does its **own** copilot onboarding — not the deterministic global-setup), **no teardown**, run
only via its own command. As **priya** for onboarding/cohort; drive gates as the role-holders.

- **Copilot-onboard the 3 segments (real LLM, well-named packs).** For each (Assess/Enforce/Closeout) drive
  `/registry/onboard`: upload the worked-example BPMN, point at its MCP (`ach-assess-mcp:8075` /
  `ach-enforce-mcp:8076` / `ach-closeout-mcp:8077`), author the trigger schema (`schemas/art.ach.*`) + triage
  (`request_type == …`), **Generate → accept as-is → publish**. **Let the copilot name the pack; capture the
  published `pack_key`** and keep the segment→pack_key map. Assert each is **active** in `GET /packs` (stable
  outcome only — never assert inferred values). Then `PUT /packs/{key}/1.0.0/cohort-membership {cohort_def_id:
  ach_exposure_cohort, correlation_key: case_id}`.
- **Close the 422 (the crux): read-and-synthesize manual-gate values at runtime.** For each manual/human gate, do
  **not** hard-code the artifact body — fetch the gate's **inferred artifact schema** at claim time (from the HITL
  task / the pack's binding schema) and **synthesize a schema-valid value** (fill required fields per type/enum).
  This is what makes the spec survive per-run schema variance (the de-risk gap).
- **Roles from the packs (data-driven, no restart).** Read each published pack's gate roles (`GET /packs/{key}`);
  grant so enforce approver ≠ assess/closeout reviewer: enforce role → **Marcus**, assess+closeout roles → **Riya**
  (priya owns). Post-onboard pending-stage/admin grant; **no service restarts**.
- **Cohort + DAG + SLA (as priya, over the captured pack_keys).** `POST /cohort/definitions ach_exposure_cohort`
  (close schema/paths from `schemas/cohort.ach_exposure.close.schema.json`); expectation graph
  `__start__ → assess → enforce → closeout → __close__` using the **captured** names; enforce→closeout arrival SLA
  `deadline 8s / at_risk 4s / wall / external`. Assert **Members 3** + the DAG/SLA read-back.
- **Run the 3 pega scenarios**, driving gates as the role-holders: `credit_approve` → 3 members / Released;
  `debit_reject` → 3 / Purged; `late_closeout` → enforce→closeout SLA **breached (external)** → 3 / Released. Assert
  the cohort reaches **MEMBERS=3 (joined & terminal) and closes** each time (poll — `expect.poll` — to absorb the
  membership read-after-write flakiness the de-risk noted; no fixed sleeps).
- **Retain everything (NO teardown)** — leave the 3 packs, the cohort + instances, and the roles for inspection.
- **Skip cleanly when the model is absent:** `copilot/generate` → `502 copilot_llm_unavailable` (or the wizard's
  "isn't reachable") → `test.skip` with a clear message. Copilot-only by design.
- **Fresh pack names per run** (the copilot names them; the non-evicting bundle-cache means reusing a name+version
  is masked) — so a re-run needs a clean DB; document it. If the cohort_def already exists, skip-with-message.

### 3. Two clean commands (no flags)
- `bash tools/e2e.sh` → the **deterministic gate** (fast, green, tears down; excludes the copilot spec).
- `bash tools/e2e-copilot.sh` → the **copilot lifecycle** (`ach-copilot-lifecycle.spec.ts` only; own project/config,
  no deterministic setup, no teardown, retains everything; skips on 502). Needs the copilot model + `mcp_stub` +
  `pega_stub`.
- Update `e2e/README.md` + `backend/docs/engineering/running-e2e-tests.md`: the two commands, their purposes
  (gate vs prod-onboarding proof), the copilot one needs the model + retains + re-run-after-wipe. Remove all flag docs.

## Do not
- Do not weaken the deterministic gate's coverage or make it depend on the LLM. Do not let the copilot spec run in
  the default `tools/e2e.sh` gate (must be its own command; non-blocking). Do not hard-code manual-gate values
  (synthesize from the inferred schema). Do not assert LLM-inferred values. Do not restart any service. Do not tear
  the copilot run down. No fixed sleeps (auto-wait/`expect.poll`). No git writes.

## Acceptance
- `bash tools/e2e.sh` (no flags) → the deterministic suite green as today, **copilot spec excluded**, tears down.
- `bash tools/e2e-copilot.sh` on a clean stack **with** the model → the copilot onboards **3 well-named ACH packs**
  (active), manual-gate values are **synthesized from the inferred schema** (no 422), roles granted from the packs
  (Marcus enforce / Riya assess+closeout / priya owns), **ach_exposure_cohort Members 3** + DAG + SLA, and
  `credit_approve`/`debit_reject`/`late_closeout` each reach **3 members / closed** (Released / Purged /
  external-breach→Released) — **nothing torn down**. **Without** the model → skips with a clear message.
- No `--copilot`/`--keep*` flags or `E2E_*` env remain; the `e2e-copilot-*` throwaway spec is gone; `tools/e2e.sh`
  takes no args.

## Final step — report
`backend/docs/_build-reports/claude_code_prompt_ach_hybrid_e2e_report.md` (uncommitted): (1) outcome; (2) the gate
left intact + the flags/throwaway removed; (3) the copilot spec — the captured pack names this run, the
**schema-read-and-synthesize** approach that closed the 422, the data-driven role split, the Members-3 + 3-flow
results, and that it retained everything; (4) the two commands; (5) verification — a green `tools/e2e.sh` gate AND a
green `tools/e2e-copilot.sh` run with the cohort retained (paste both), plus the no-model skip; (6) residual
fragilities that remain (and why they're now non-blocking). One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `e2e/` + `tools/` + docs only. Deterministic suite stays
the reliable gate (flags stripped); one defensive, skippable, retains-everything copilot lifecycle spec on its own
command; manual-gate values synthesized from the inferred schema; no service restarts; two clean commands, zero flags.
