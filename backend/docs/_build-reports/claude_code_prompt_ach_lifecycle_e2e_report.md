# ACH full-lifecycle e2e — onboard → SoD-aware access → cohort/DAG/SLA → multi-flow (incl. SLA breach)

**Outcome:** a flagship `e2e/tests/ach-lifecycle.spec.ts` drives the whole ach_exposure use case from a clean stack —
3 segments onboarded as priya with **SoD preserved**, access **distributed across Riya/Marcus straight from the
pack's SoD**, a structural SoD check, the cohort DAG + enforce→closeout SLA, and three pega_stub flows
(**credit_approve → Released**, **debit_reject → Purged**, **late_closeout → external SLA breach + Released**), all
asserted in the UI. All 5 tests green; hitl-arc still green (now role-aware). No git writes.

## 1. SoD-preserving onboarding + the SoD the ACH packs now declare
`onboard_ach.py` stopped sending `sod_policies: []`; the **enforce** pack now commits the rule-based inference's
`distinct_actor` constraints (services/inference.py `sod_candidates`: a *draft*-hint node paired with an
*approve*-hint node in a different lane):
```
distinct_actor [Task_PrepareRelease, Task_AuthorizeRelease]
distinct_actor [Task_PrepareRelease, Task_AuthorizePurge]
```
This is a **human ↔ capability** shape: `Task_PrepareRelease` ("Prepare release…") is a CAPABILITY (drafter);
`Task_AuthorizeRelease`/`Purge` are the HUMAN approval gates. So it is **structurally declared** but **inert at
runtime** — `compute_sod_excluded` (engine/hitl.py) only excludes a HUMAN who acted on a `distinct_actor` sibling,
and the drafter is a capability with no human actor, so no human is ever excluded. Assess/closeout infer **no** SoD
(no approve-hint task). This is exactly the prompt's "abide, not behaviourally-rejectable" shape — see §3.

## 2. SoD-aware access distributed FROM the pack (not hardcoded)
`_role_persona()` reads the committed SoD and splits the gate roles: a role whose element is named in a
`distinct_actor` constraint (the enforce **approval** gate) → the **approver** persona **marcus**
(`role.payments.ops_approver`); every other gate role (assess + closeout) → the **analyst** persona **riya**
(`role.payments.ops_analyst`). Grants go through the pending-stage/admin path (per-persona). The UI enforces
role-holding, so the browser must act as the SoD-correct persona — a new **role-aware** selector
`personaForRole(pool, role, excluded)` (backend.ts) picks the pool persona who HOLDS the gate role and isn't
SoD-excluded. The reused gate loop (and hitl-arc) now use it, so gates are driven by riya (assess/closeout) and
marcus (enforce). The runtime API is role-agnostic, so **pytest smoke is unaffected**.

## 3. Structural + behavioural SoD assertions
- **Structural (`ach-lifecycle` test 1):** read `GET /packs/ach-decision-enforce/1.0.0` → assert
  `policies.separation_of_duties` has a `distinct_actor` over an authorise gate (four-eyes DECLARED), map that gate +
  the assess gate to their roles from the bindings, and assert those roles are **held by DISTINCT personas**
  (approver ≠ assessor) — the access distribution abides the pack's SoD.
- **Behavioural:** ACH's SoD is human↔capability, so **same-actor rejection is NOT assertable** (no second human in
  one instance; `task.excluded` is always empty). Per the prompt, we **abide** — distinct people across the flow via
  the role distribution — rather than forcing a rejection the declared SoD doesn't imply. The role-aware loop still
  exercises the SoD-correct/excluded selection; it's just always empty for this pack's shape. (A two-human pack would
  hit the exclusion path in the same loop.)

## 4. Cohort + DAG + SLA
`ensure_cohort_definition()` creates `ach_exposure_cohort` (owner-gated, as priya) with the graph
`__start__ → assess → enforce → closeout → __close__` and the enforce→closeout **arrival** SLA (owner **external**,
clock wall). Test 2 asserts the DAG nodes + that the enforce→closeout edge carries an external-owned SLA.

## 5. The flows + the SLA-breach assertion
Each flow builds a Scenario variant (pega_stub scenario + human outputs + expected outcome), fires via the run-scoped
`fireScenario` (case_id = `${RUN_ID}-N`), drives the reused role-aware gate loop, and asserts off the UI:
- **credit_approve** → assess (riya) → **AuthorizeRelease** (marcus) → closeout (riya) → **closed / Released**.
- **debit_reject** → reject branch → **AuthorizePurge** (marcus) → **closed / Purged**.
- **late_closeout** → the closeout is delayed 25s → the enforce→closeout arrival SLA **BREACHES (owner=external)** and
  the case still **closes Released**. Asserted in GLEA (`sla.breaches.external ≥ 1`, a `breached` state with
  `owner=external`) **and** on the cohort SLA board (`/cohorts/by-correlation/<case>`): "Breaches by owner:" →
  `external: 1`, a "Breached" SLA-state chip.

## 6. Verification
- `npx playwright test ach-lifecycle` → **5 passed** (credit_approve 14s, debit_reject 14s, late_closeout 39s).
- Full `bash tools/e2e.sh` from clean → all journeys green incl. **hitl-arc** (role-aware). pytest smoke + webui
  build/vitest untouched (no changes to their sources).
- **Deterministic SLA breach — the one real gotcha:** `SLA_POLL_SECONDS=15` vs the worked example's 20s deadline /
  25s pega delay leaves only a 5s breach window → a poll lands in it ~⅓ of runs; otherwise the late arrival **voids**
  the SLA (excused, terminal — not a breach) and the test flakes (observed: one run showed `('external','voided')`).
  Fix (in-scope — pega_stub is fixed at 25s and out of scope): the e2e cohort def uses **deadline 8s** so the breach
  window (8→25s = 17s) **exceeds** the 15s poll → a poll is guaranteed to fire the breach before arrival. 8s still
  clears the immediate-closeout flows (~1–3s arrival → satisfied). Confirmed with `--repeat-each=3` on late_closeout.

## 7. Follow-ups
- ACH has no two-human-in-one-instance gate, so behavioural four-eyes rejection isn't demonstrable here; a pack whose
  `distinct_actor` pairs two human gates would exercise the exclusion path in the same loop (the machinery is ready).
- The e2e's 8s SLA deadline deviates from ONBOARDING.md's illustrative 20s purely for deterministic breach detection
  against the 15s poller; if `SLA_POLL_SECONDS` is lowered in dev, the deadline could return toward 20s.
