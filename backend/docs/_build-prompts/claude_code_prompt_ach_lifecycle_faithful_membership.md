# Claude Code prompt — make the ACH lifecycle e2e FAITHFUL to the real process (3-member cohort, correct gates, real membership assertion)

The ACH lifecycle journey passes but does **not** reflect the real `ach_exposure` process, and can leave the cohort
with **1 member instead of 3**. Fix the onboarding to match the BPMNs, and make the test **require** a correct
3-member cohort. Understand the use case first: `backend/docs/methodology/worked-examples/ach_exposure`
(ONBOARDING.md + the three BPMNs). **No service restarts anywhere** (identity/config-forge/notification stay up;
the tests already don't restart them — keep it that way).

## Root cause (diagnosed from the BPMNs + the run)
Real HITL shape (from the `.bpmn` files):
- **A — `ach-exposure-assess`: fully automated.** All `serviceTask`s (classify → risk-profile → recommend → draft
  → **Notify Pega**); **no `userTask`, no gate.**
- **B — `ach-decision-enforce`:** `userTask`s `Task_AuthorizeRelease` (approve) / `Task_AuthorizePurge` (reject) —
  the enforce approval gate (`approve_actions`, `role.ach_decision_enforce.approver`).
- **C — `ach-closeout`:** `userTask` `Task_ReviewArtifacts` — the closeout review gate
  (`role.ach_closeout.reviewer`).

**Bug:** `e2e/fixtures/onboarding/onboard_ach.py` gates **`Task_NotifyAssessed` (a serviceTask!) on A with
`approve_actions`** (a workaround for the notify_pega side-effect hitl-guard). That fabricates a human gate on the
automated assess segment → if it isn't driven, **A stays Running, never hands back, Pega never fires B/C → the
cohort stalls at 1 member**. Pega fires A → B → C on each `notify_pega` handback (ONBOARDING.md §4), so A must
auto-complete for the cohort to reach 3 members.

## Deliverables

### 1. Onboard the 3 segments faithfully (`onboard_ach.py`)
- **A (assess): NO human gate.** Remove the `Task_NotifyAssessed: approve_actions` gate. Bind `notify_pega` (and
  A's other caps) as **not** side-effectful so the assemble hitl-guard doesn't demand a gate (the setup already
  derives `suggested_side_effect` from whether the pack gates a tool — line ~163 — so simply *not* gating it makes
  A onboard gateless). A must commit clean and run **fully automatically** (assess → notify Pega handback).
- **B (enforce): keep the real gate** on `Task_AuthorizeRelease` / `Task_AuthorizePurge` (`approve_actions`,
  `role.ach_decision_enforce.approver`) — the money-moving action gate.
- **C (closeout): keep the real gate** on `Task_ReviewArtifacts` (`role.ach_closeout.reviewer`).
- Confirm all three commit clean (200) with this shape; cohort membership stays set on **all three**
  (`PUT /packs/{key}/1.0.0/cohort-membership → cohort_def_id: ach_exposure_cohort, correlation_key: case_id`).

### 2. Roles — two users, post-onboard, no restart
- **priya**: seeded owner (onboards, creates cohort). **Marcus**: grant `role.ach_decision_enforce.approver`
  (drives B). **Riya**: grant `role.ach_closeout.reviewer` (drives C). Granted **after** onboarding via the
  existing pending-stage/grant path (roles can only be assigned post-onboard). **No assess role** — A is automated.
  Two distinct humans (Marcus on B, Riya on C) satisfy the "two users" requirement naturally; teardown revokes both.
- The base persona roles are **seeded** (do not restart identity to "repair" them; if they're genuinely missing
  that's an environment issue, out of scope — the test only adds the `ach_*` roles).

### 3. Cohort definition — verify true 3-member membership
- The definition `ach_exposure_cohort` (created by priya with the DAG + enforce→closeout SLA) must show **Members
  3** once the packs are onboarded (membership comes from each pack's `cohort_membership`). **Assert structurally**
  the definition reports all three pack members.

### 4. The membership assertion that would have caught this
- For each driven flow, **assert the cohort instance reaches all 3 members joined and terminal, then closes** — not
  merely "closed". Concretely: the cohort instance for the case shows **MEMBERS = 3** (assess, enforce, closeout all
  joined), all member processes terminal, lifecycle **closed**, outcome as expected. A cohort stuck at 1 member (A
  running) must **fail** the test. (Read from the Cohorts instance detail / GLEA.)

### 5. Drive the flows per the real shape
- Fire via pega_stub; A **auto-completes** (no gate to drive), then drive **B** as **Marcus** and **C** as **Riya**
  through the Task Inbox, to close:
  - **credit_approve** → B `AuthorizeRelease` (Marcus) → C `ReviewArtifacts` (Riya) → **3 members, closed / Released**.
  - **debit_reject** → B `AuthorizePurge` (Marcus) → C (Riya) → **3 members, closed / Purged**.
  - **late_closeout** → enforce→closeout arrival SLA **breaches (external)**, closeout arrives late, still closes;
    **3 members**. (Keep the deterministic 8s deadline already in place.)
- The role-aware gate loop drives each gate as the persona holding its role; A contributes no gate.

### 6. Reality notes (keep, don't fake)
- ACH has **no within-instance two-human gate**, so SoD is cross-segment (B-approver ≠ C-reviewer, different
  instances) and **not runtime-rejectable** — the test abides by distributing the two gates to distinct people
  (Marcus/Riya) and asserting the flow completes, **not** by attempting a same-actor rejection. Keep the structural
  SoD read ("the pack declares what it declares").

## Do not
- Do not fabricate gates the BPMN doesn't have (the A-gate bug). Do not restart identity/config-forge/
  notification-service (or any service) from the test/setup. Do not assert LLM-inferred values. Do not let a
  1-member / stalled cohort pass. No fixed sleeps. No git writes.

## Acceptance
- From a clean stack (services up, seeded roles, empty DB, mcp_stub + pega_stub up), `bash tools/e2e.sh` green
  with the ACH lifecycle **faithful**: A onboards **gateless** and runs automatically; B/C keep their real human
  gates driven by **Marcus/Riya**; the definition shows **Members 3**; and **every driven flow's cohort reaches 3
  joined+terminal members and closes** (credit_approve→Released, debit_reject→Purged, late_closeout→external breach
  then Released) — a stalled 1-member cohort **fails**. No service is restarted by the run.
- Idempotent/re-runnable; degrades to a clean skip when the stack/pega_stub is absent; other journeys + pytest
  smoke untouched.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_ach_lifecycle_faithful_membership_report.md` (uncommitted):
(1) outcome one-liner; (2) the A-gate removal (A now automated) + proof all three commit clean; (3) the role
distribution (Marcus→B, Riya→C, post-onboard, no restart); (4) the Members-3 structural check + the per-flow
3-member-joined-and-closed assertion (the one that catches the stall); (5) the three flows' results incl. the SLA
breach; (6) verification — a green run from clean showing MEMBERS=3 per flow; (7) confirmation nothing restarts
services. One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `e2e/` + `onboard_ach.py` + docs only. Faithful to the
ACH BPMNs (A automated; B/C human gates), true 3-member cohort asserted, two users (Marcus/Riya) for the two real
gates, no service restarts, no fabricated gates.
