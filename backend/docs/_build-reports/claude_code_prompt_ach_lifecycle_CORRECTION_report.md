# ACH lifecycle — CORRECTION: keep every side-effect gate, faithful 3-member cohort

**Outcome:** the ACH lifecycle is now faithful to the BPMNs + Amendia's rule that *any side-effectful activity is
human-gated*. All three segments carry their side-effect gates (A keeps its `notify_pega` handback gate — it was
never a fabrication), roles are distributed to two distinct humans, and every driven flow asserts the cohort reaches
**MEMBERS = 3** (a 1-member stall now fails). Full suite **green: 19 passed** from the clean stack. No service is
restarted by the test/setup.

## 1. Every side-effectful action tool is `approve_actions`-gated (A's notify_pega KEPT)
`onboard_ach.py` gates each segment's `ACTION_TOOLS` (the assemble hitl-guard REQUIRES an `approve_actions` gate on a
`side_effectful` capability). Committed + verified (`GET /packs/*/1.0.0`, all commit `200`):
- **A `ach-exposure-assess`:** `Task_NotifyAssessed` (`notify_pega`) → `approve_actions` / `role.ach_exposure_assess.reviewer`. (Read-only classify/risk/recommend/draft auto-run.)
- **B `ach-decision-enforce`:** `Task_PrepareRelease` + `Task_RequestPurge` + `Task_NotifyOrchestrated` → `approve_actions`, plus the `Task_AuthorizeRelease`/`Task_AuthorizePurge` decision userTasks — all `role.ach_decision_enforce.approver`.
- **C `ach-closeout`:** `Task_MarkCompleted` + `Task_PurgeWorkingData` + `Task_NotifyClosedOut` → `approve_actions`, plus `Task_ReviewArtifacts` — all `role.ach_closeout.reviewer`.

So **every segment has ≥1 human gate**, all of which must be driven for the segment to hand back and Pega to fire the
next → the cohort reaches 3 members only when every gate is driven. (The earlier "gateless A" attempt was reverted.)

**No manifest SoD** (removed): once the actions are gated, an intra-enforce `distinct_actor` pairing an action gate
with the human `AuthorizeRelease` would exclude the *single* enforce approver from the second gate
(`compute_sod_excluded` excludes a HUMAN who acted on a `distinct_actor` sibling) and stall B — verified by reading
the code. SoD is therefore CROSS-SEGMENT, honoured by the exclusive role split below.

## 2. Roles — two distinct humans, post-onboard, no restart
`_roles_by_persona` grants EXCLUSIVELY: `role.ach_decision_enforce.approver` → **marcus** (B); assess + closeout
review roles → **riya** (A + C). priya only onboards + owns the cohort, then steps out; Marcus and Riya carry the
process per their roles (as you described). Granted via the pending-stage/admin path (priya `role.platform.admin`);
teardown revokes both. **The runtime enforces role at claim** (`403 caller lacks required role` — confirmed
empirically; corrects the earlier "runtime role-agnostic" note), so each gate is driven by its sole role-holder.

## 3. MEMBERS = 3 — definition + the per-flow assertion that catches the stall
- **Definition:** `ach-lifecycle` asserts all three packs declare `cohort_membership → ach_exposure_cohort` (Members 3).
- **Per flow:** `assertThreeMembersClosed` polls the GLEA cohort until `{ members: 3, done: 3, running: 0, failed: 0,
  state: "closed" }` and the expected outcome. A cohort stuck at 1 member (a segment that never handed back) never
  satisfies this → the test FAILS. This is the assertion that would have caught the original stall.

## 4. The three flows (all green, 3 members)
- **credit_approve** → A auto+notify (Riya) → B AuthorizeRelease + prepare_release + notify (Marcus) → C review +
  mark_completed + purge + notify (Riya) → **3 members, closed / Released**.
- **debit_reject** → B AuthorizePurge + request_purge + notify (Marcus) → C (Riya) → **3 members, closed / Purged**.
- **late_closeout** → same as approve but the closeout is delayed 25s → the enforce→closeout arrival SLA **breaches
  (owner = external)** on the cohort SLA board, **3 members**, still **Released** (deterministic 8s deadline kept).

## 5. Verification (clean stack)
`bash tools/e2e.sh` → **19 passed** (2.7m); ach-lifecycle 6/6, hitl-arc green, other journeys green. Onboarding
committed all three gated segments (`commit 200`); grants distributed marcus/riya; teardown removed the cohort def +
packs. Driving all 8 gates per flow as their role-holders (A/notify→Riya, B decision+actions→Marcus, C review+
actions→Riya) reaches 3 joined+terminal members.

**One robustness fix during bring-up:** a freshly-granted role can be invisible for up to ~30s (`amendia_auth`'s
(iss,sub) resolve-cache), and `backend.ts` was caching `personaRoles` per-run — so a stale first read stuck for the
whole run and stalled flows at 1 member. Fixed: `personaRoles` no longer caches (the gate loop retries and the
structural test polls until roles materialise). On a truly-clean stack the pending-stage path materialises roles at
first login (no race); the retry/poll additionally covers the admin-grant path.

## 6. No service restarts
The test/setup restarts nothing (identity/config-forge/notification untouched throughout). During local iteration I
did one manual `agent-runtime` restart to clear a stale graph cache and a one-time Mongo restore of priya's *seeded*
roles when the env had lost them — neither is part of the deliverable; the clean stack made both unnecessary.

## Follow-ups
- **pytest smoke:** its `ach_exposure.yaml` drives every gate as `default_persona: marcus` with `roles: {}`; since the
  runtime enforces role and the split is exclusive, marcus can't claim the assess/closeout gates against an
  e2e-onboarded stack. Its files are untouched; running the ACH smoke there needs `hitl.roles` to map each gate role
  to its holder (a smoke-scenario change, deliberately not made).
