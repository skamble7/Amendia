# Claude Code prompt — ACH full-lifecycle Playwright e2e (onboard → SoD-aware access → cohort+DAG+SLA → multi-flow execution incl. SLA breach)

A flagship end-to-end acceptance journey for the **ach_exposure** use case
(`backend/docs/methodology/worked-examples/ach_exposure` — one cohort, three segments, pega_stub as the external
orchestrator). From a clean stack: onboard the 3 segments **as Priya**, grant access to **Marcus + Riya** **as the
pack's declared separation-of-duties requires**, create the cohort with its DAG + SLA, and drive multiple flows via
pega_stub — approve, reject, and an **SLA breach** — asserting outcomes in the UI. Builds on the existing `e2e/`
suite (reuse its page objects, drivers, personas, `--keep`).

**Guiding principle (Sandeep): the test is DATA-DRIVEN by the pack.** Whatever SoD/4-eyes the pack declares
(`manifest.policies.separation_of_duties`), the test **reads it and abides** — it does not hardcode a 4-eyes rule.

## Key facts (verified — build on these)
- SoD is enforced at decide-time from the pack: `agent-runtime/app/engine/engine.py` reads
  `bundle.manifest.policies.separation_of_duties` → `compute_sod_excluded(sod_policies, actor_log, element_id)`
  (`engine/hitl.py`) excludes a user from a gate if they already acted on a **`distinct_actor`** sibling **in the
  same instance's actor log**. So `distinct_actor` between two **human** gates in one instance is genuinely
  enforced; a constraint pairing a human with an automated capability has no second human to exclude.
- The four-eyes inference (`process-registry/app/services/copilot/reconcile.py::detect_approval_gates` +
  `inference.py` `sod_candidates`) is **rule-based / deterministic** — so a copilot-free onboarding can reproduce it.
- **The current deterministic setup STRIPS SoD:** `e2e/fixtures/onboarding/onboard_ach.py` sends
  `"sod_policies": []`. This must change to **preserve** the inferred SoD (see Deliverable 1).

## Read first
- `e2e/fixtures/onboarding/onboard_ach.py` — the deterministic (copilot-free) 3-segment onboarding as **priya**;
  the `set_policies` call that currently drops SoD; `grant`/pending-stage of gate roles; teardown.
- `e2e/tests/{hitl-arc,cohorts,dag-sla-editor}.spec.ts`, `e2e/pages/*`, `e2e/support/{drivers,personaPage,backend}.ts`
  — the gate-driving loop, cohort screens, the DAG/SLA editor flow, the pega_stub/stub drivers, per-persona pages.
- `backend/services/process-registry/app/routers/cohort.py` — `POST /cohort/definitions` (owner-gated) for the
  cohort + expectation-graph/SLA; the graph/SLA shape (ADR-063/064).
- `pega_stub/src/pega_stub/scenarios.py` — the scenarios: `credit_approve`, `debit_reject`, `route_uw`,
  `late_closeout` (the SLA-breach one). `pega_stub` `POST /cases`.
- `backend/docs/methodology/worked-examples/ach_exposure/ONBOARDING.md` — the intended flow, the SoD note
  (assessor ≠ enforce approver), the cohort DAG + the enforce→closeout SLA, the `late_closeout` breach.
- `backend/services/platform/identity/app/routers/admin.py` + `pending.py` — role grant / pending-stage to
  distribute roles across **two** personas.

## Deliverables

### 1. Onboard the 3 segments as Priya — **preserve the inferred SoD** (`onboard_ach.py`)
- Stop forcing `sod_policies: []`. Instead include the **deterministically-inferred `distinct_actor`** constraint(s)
  for each segment (compute from the reconcile/inference SoD detection, or hardcode the exact constraint the
  rule-based inference produces for the enforce segment) so the **committed packs carry whatever 4-eyes onboarding
  infers**. Owner-gated (priya's token), as today.
- Everything else stays deterministic/copilot-free (fast, reproducible).

### 2. SoD-aware access — grant across Marcus + Riya **from the pack** (not hardcoded)
- After onboarding, **read each pack's `policies.separation_of_duties`** (`GET /packs/{key}`). For each
  `distinct_actor` constraint, identify the **human** gate roles it pairs, and distribute the gate roles so the
  paired gates can be performed by **distinct** personas — e.g. assess role → **Riya**, enforce role → **Marcus**
  (derive the split from the constraint; don't assume a fixed mapping). Use the identity grant/pending-stage path.
- Non-constrained gate roles: grant normally (either persona).

### 3. Structural SoD check — "looking at the pack"
- Assert the committed pack **declares** the expected SoD (`policies.separation_of_duties` non-empty with a
  `distinct_actor` where onboarding inferred one), and that the access distribution (Deliverable 2) **abides** by it
  (the constrained human gates are held by distinct personas). This validates the 4-eyes is *present*, from the pack.

### 4. Behavioral SoD enforcement — abide where it's enforceable
- For a `distinct_actor` pairing **two human gates in the same instance**: drive the first gate as actor **X**, then
  assert the runtime **excludes X** from the second gate (the UI shows X ineligible / the decision is refused —
  `compute_sod_excluded`), and a **distinct** actor **Y** completes it. This proves 4-eyes is *enforced*.
- If the pack's SoD pairs a human with an **automated** drafter (no second human), there is nothing to reject —
  the test **abides** by using distinct people across the flow and completing, and the report notes that shape is
  not behaviorally rejectable. **Let the pack decide which case applies** — do not force a rejection that the
  declared SoD doesn't imply.

### 5. Cohort + DAG + SLA as Priya
- Create `ach_exposure_cohort` via `POST /cohort/definitions` (or the UI, owner-gated) with the expectation graph
  `__start__ → assess → enforce → closeout → __close__` and the **enforce→closeout arrival SLA** (the breach
  target — deadline/at-risk/clock/owner=external, per ONBOARDING.md). This is the DAG + SLA the breach flow tests.

### 6. Multi-flow execution via pega_stub (incl. SLA breach)
Drive several flows, each end-to-end through the UI with the **SoD-correct personas**, asserting outcomes off the
screens:
- **credit_approve** → assess gate (Riya) → enforce **AuthorizeRelease** (Marcus) → closeout → cohort **closed /
  Released**.
- **debit_reject** → the reject branch → **AuthorizePurge** (the purge path) → cohort closed (purge outcome).
- **late_closeout** → the enforce→closeout **arrival SLA breaches** — assert the cohort's SLA board shows the
  breach (**owner = external**, **arrived-late**) and the case still closes.
Reuse the existing gate-driving loop (enable-aware/persist-aware) + the pega_stub driver; per-gate persona from the
SoD distribution.

### 7. Structure, degrade, teardown
- A flagship `e2e/tests/ach-lifecycle.spec.ts` (or a well-named describe) composing the above, reusing existing
  page objects/drivers — don't duplicate logic. Degrade (skip with a clear message) if the stack/pega_stub is down.
  Teardown as today (revoke both personas' roles, delete cohort def + packs); honor `--keep`/`--keep-copilot`.
- Fire cases with a **run-scoped correlation prefix** so teardown/inspection can identify this run's data.

## Do not
- Do not hardcode the 4-eyes — **read it from the pack** and abide; do not force a rejection the declared SoD
  doesn't imply. Do not strip inferred SoD in onboarding. Do not use the copilot/LLM in this (deterministic) path.
- Do not assert LLM/inferred *values*; assert declared SoD presence, role distribution, enforcement (where two
  human gates), terminal/cohort/SLA outcomes. No fixed sleeps. No git writes.

## Acceptance
- From a **clean** stack, `bash tools/e2e.sh` (this journey included) is **green**: the 3 ACH segments onboard as
  priya **with SoD preserved**; the test **reads the pack's SoD** and distributes assess/enforce roles across
  **Riya/Marcus** accordingly; the structural check confirms the 4-eyes is declared + abided; where two human gates
  are paired, **same-actor is excluded and a distinct actor completes**; the cohort + DAG + enforce→closeout SLA is
  created; **credit_approve** closes Released, **debit_reject** takes the purge branch, and **late_closeout**
  **breaches the SLA (external, arrived-late)** and still closes — all asserted in the UI.
- Deterministic + idempotent (re-runnable); degrades to a clean skip when the stack/pega_stub is absent; existing
  journeys + pytest smoke + webui build/vitest untouched.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_ach_lifecycle_e2e_report.md` (uncommitted): (1) outcome
one-liner; (2) the SoD-preserving onboarding change + the **actual** SoD the ACH packs now declare (elements +
whether two-human or human+capability); (3) how access is distributed **from the pack** across Riya/Marcus, and the
structural + behavioral SoD assertions (incl. whether same-actor-rejection was assertable for ACH's shape); (4) the
cohort/DAG/SLA setup; (5) the flows driven (approve/reject/late_closeout) + the SLA-breach assertion; (6)
verification — a green run from clean, per-flow; (7) follow-ups. One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `e2e/` + `onboard_ach.py` + docs only; reuse the existing
gate loop, drivers, cohort/SLA editor, and persona/role plumbing. Deterministic, data-driven-by-the-pack SoD,
degrade-don't-error, multi-flow incl. the SLA breach — the full ACH lifecycle as one acceptance narrative.
