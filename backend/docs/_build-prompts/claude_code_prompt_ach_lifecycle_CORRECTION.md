# Claude Code prompt — **CORRECTION / SUPERSEDES** the previous ACH-lifecycle prompt (do NOT remove segment A's gate)

**STOP — this replaces `claude_code_prompt_ach_lifecycle_faithful_membership.md`.** That prompt was wrong on its
central instruction: it said segment A is "fully automated, remove the `Task_NotifyAssessed` gate, bind
`notify_pega` as not side-effectful." **Do NOT do that.** Sandeep's rule (and the code): **any side-effectful
activity is human-gated by default** — and Amendia *enforces* it.

## The correct rule (verified)
- `process-registry` assemble **hitl-guard** (`onboarding.py::_check_hitl_guard`, ~L824):
  `if side_effect == "side_effectful" and not hitl_mode_at_least(mode, APPROVE_ACTIONS): error`. A side-effectful
  capability **must** carry an `approve_actions` (human) gate. `suggested_side_effect` is declared by the **tool**,
  not chosen by the pack.
- The MCP stubs declare the side-effectful **action tools** per segment (`ACTION_TOOLS`):
  - **A `ach-exposure-assess`:** `{notify_pega}` → the Pega handback is side-effectful ⇒ **gated** (this is the
    `Task_NotifyAssessed` gate — it is **correct**, not a fabrication; A is *not* gateless).
  - **B `ach-decision-enforce`:** `{prepare_release, request_purge, notify_pega}` — all side-effectful ⇒ gated,
    plus the `Task_AuthorizeRelease`/`Task_AuthorizePurge` decision `userTask`s.
  - **C `ach-closeout`:** `{mark_completed, purge_working_data, notify_pega}` — all side-effectful ⇒ gated, plus
    the `Task_ReviewArtifacts` `userTask`.
- So **every segment has ≥1 human gate** (at minimum its `notify_pega` handback approval). The BPMN task type
  (serviceTask) is irrelevant — the **binding's HITL mode** makes a side-effectful capability a gate.

## What was actually wrong (not a fabricated gate)
The cohort stalls at **1 member** when a **legitimate** gate isn't driven (so the segment never hands back → Pega
never fires the next segment). The fix is **not** to delete gates — it's to onboard **faithfully** (every
side-effectful action tool `approve_actions`-gated), **drive every gate**, and **assert the cohort reaches 3
members**. Any earlier onboarding that *suppressed* a `notify_pega` side-effect (marking it not-side-effectful to
avoid a gate) is the unfaithful part — undo that too.

## Deliverables (revised)

### 1. Onboard the 3 segments faithfully — gate every side-effectful action tool (`onboard_ach.py`)
- Mark each segment's `ACTION_TOOLS` (above) **side-effectful** and bind them **`approve_actions`** — do **not**
  suppress the side-effect to dodge a gate. Concretely per segment:
  - **A:** `notify_pega` gated (`role.ach_exposure_assess.reviewer`). A now correctly has its handback-approval gate.
  - **B:** `prepare_release`/`request_purge`/`notify_pega` gated + the `AuthorizeRelease`/`AuthorizePurge` decision
    (`role.ach_decision_enforce.approver`).
  - **C:** `mark_completed`/`purge_working_data`/`notify_pega` gated + `ReviewArtifacts`
    (`role.ach_closeout.reviewer`).
- All three commit clean; `cohort_membership → ach_exposure_cohort (case_id)` on all three (as today).

### 2. Roles — distributed for the gates, post-onboard, NO restart
- **priya** seeded owner. Grant (post-onboard, pending-stage) the gate roles so every gate can be driven:
  `role.ach_exposure_assess.reviewer` + `role.ach_closeout.reviewer` → **Riya**;
  `role.ach_decision_enforce.approver` → **Marcus**. (Keep the SoD-derived split; two distinct humans across the
  segments.) **Do not restart identity/config-forge/notification** — base roles are seeded; the test only adds the
  `ach_*` roles. Teardown revokes them.

### 3. Drive EVERY gate; assert a true 3-member cohort
- Fire via pega_stub; drive **all** gates in each segment through the Task Inbox as the persona holding the role
  (A's handback approval → Riya; B's decision + actions → Marcus; C's review + actions → Riya). Each segment must
  reach its handback so Pega fires the next.
- **Assert the cohort instance reaches MEMBERS = 3 (assess+enforce+closeout all joined & terminal) and closes** —
  not merely "closed". A 1-member / stalled cohort **fails**. Also assert the **definition** shows **Members 3**.
- Flows: `credit_approve` → 3 members, closed/Released; `debit_reject` → 3 members, closed/Purged; `late_closeout`
  → 3 members, enforce→closeout SLA **breached (external)**, closes Released (keep the 8s deadline).

## Do not
- **Do not remove segment A's gate; do not mark `notify_pega` (or any action tool) not-side-effectful.** Side-effect
  ⇒ `approve_actions` gate, always. Do not restart any service from the test/setup. Do not let a stalled 1-member
  cohort pass. No fixed sleeps. No git writes.

## Acceptance
- From a clean stack (seeded roles, empty DB, mcp_stub + pega_stub up): `bash tools/e2e.sh` green with A/B/C each
  carrying their side-effect gates, all gates driven by priya-granted Riya/Marcus, the definition at **Members 3**,
  and **every driven flow's cohort at 3 joined+terminal members, closed** (approve→Released, reject→Purged,
  late_closeout→external breach then Released). No service restarted. Other journeys + pytest smoke untouched.

## Final step — report
`backend/docs/_build-reports/claude_code_prompt_ach_lifecycle_CORRECTION_report.md`: (1) outcome; (2) confirm every
side-effectful action tool per segment is `approve_actions`-gated (A's `notify_pega` **kept**), the per-segment gate
list, and all three commit clean; (3) role distribution (Riya: assess+closeout, Marcus: enforce; post-onboard, no
restart); (4) the MEMBERS=3 definition check + per-flow 3-joined-and-closed assertion; (5) the three flows incl. the
SLA breach; (6) a green run from clean showing MEMBERS=3 per flow; (7) confirm nothing restarts services. One screen.

## Working agreement
No git write commands — leave the tree dirty. `e2e/` + `onboard_ach.py` + docs only. Faithful side-effect gating on
all three segments (A keeps its `notify_pega` gate), true 3-member cohort asserted, two users (Riya/Marcus) for the
gates, no service restarts. This **supersedes** the prior prompt's "remove A's gate" instruction.
