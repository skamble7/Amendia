# Hybrid ACH e2e — deterministic gate kept, defensive copilot lifecycle added, flag clutter removed

**Outcome.** The e2e is now **two clean commands, no flags**. `tools/e2e.sh` stays the **reliable CI gate**
(deterministic onboarding, always tears down) and is verified **green: 19 passed**. `tools/e2e-copilot.sh` is a new
**separate, non-blocking** command that proves the **real copilot onboarding path** end to end — verified
**green: 4 passed (4.5m)** against the live LLM: it onboards the 3 ACH segments via the autopilot, forms the cohort,
drives the 3 pega flows to **3 members / closed**, and **retains everything**; it skips cleanly when the model is
absent. The confusing flag maze (`--copilot` / `--keep` / `--keep-copilot` + `E2E_COPILOT` / `E2E_KEEP` /
`E2E_KEEP_COPILOT`) and the throwaway `copilot-onboarding.spec.ts` are gone.

## 1. The deterministic gate — intact, flags removed (still the CI gate)
- **Coverage untouched.** Every deterministic spec, `onboard_ach.py`, and the deterministic `global-setup.ts` are
  **unchanged**. The gate still onboards the 3 ACH segments deterministically, runs all journeys, and tears down.
- **Flags removed only.** `tools/e2e.sh` is now a single no-arg command; `e2e/support/env.ts` lost `KEEP_STACK` /
  `COPILOT_ENABLED` / `KEEP_COPILOT`; `e2e/global-teardown.ts` dropped the `KEEP_STACK` branch (it **always** tears
  down now). `playwright.config.ts` gained `testIgnore: ["**/ach-copilot-lifecycle.spec.ts"]` so the copilot spec is
  **excluded** from the gate.
- **Throwaway deleted.** `e2e/tests/copilot-onboarding.spec.ts` (the misleading single `e2e-copilot-*` pack) is
  removed — superseded by the real copilot lifecycle spec.

## 2. The copilot lifecycle spec — `e2e/tests/ach-copilot-lifecycle.spec.ts` (defensive, retains, skippable)
Its own `playwright.copilot.config.ts` + `global-setup.copilot.ts` (persona logins only — **no** deterministic ACH
onboarding, **no** teardown). As priya it drives the **real** `/registry/onboard` autopilot to onboard the 3
segments (fresh pack keys `ach-copilot-<seg>-<stamp>` per run), captures each published `pack_key`, sets cohort
membership, distributes the gate roles **read from the packs** (enforce → marcus, assess+closeout → riya), creates
its own `ach_copilot_cohort` (distinct from the gate's `ach_exposure_cohort`, so the two never collide) over the
captured keys with the enforce→closeout external SLA, and runs the 3 pega flows.

- **The 422 fix — schema-read-and-synthesize.** A manual gate's output artifact carries a **copilot-inferred** JSON
  schema. `support/copilot.ts::synthesizeManualGateEdits` reads the gate task's editable artifacts, fetches each
  one's inferred schema (ADR-060 pack-scoped `GET /packs/{key}/{ver}/artifact-schemas/{k}/{v}`), and **synthesizes a
  schema-valid value** (required fields per type/enum; `case_id`→correlation; booleans→approve; respects
  `additionalProperties:false`). This is what let the de-risk's blocked enforce gate submit without a 422. **No
  manual-gate value is hardcoded.**
- **Data-driven, SoD-robust roles.** `packGateRoles` reads every gate role a pack declares (copilot-named, per-run).
  The copilot frequently infers a **4-eyes `distinct_actor` SoD *within* enforce** (e.g. `Task_AuthorizeRelease` vs
  `Task_PrepareRelease`) — once marcus authorises the release he is SoD-excluded from the paired action gate, and a
  **single** enforce approver then stalls the segment (verified live: `distinct_actor[Task_PrepareRelease|
  Task_AuthorizeRelease]: usr-… already acted on Task_AuthorizeRelease`, cohort stuck at 2 members). With only two
  process humans (priya owns + steps out), the SoD-correct distribution is to grant **every** gate role to **both**
  marcus and riya and drive each gate with the **SoD-aware picker** (marcus first; riya provides the second
  signature when marcus is excluded — `personaForRole`). The structural assertion: both hold every gate role (4-eyes
  satisfiable), priya holds none. (This is why the prompt's clean "enforce→marcus only" split had to yield — it is
  mathematically incompatible with a copilot-inferred 4-eyes enforce SoD.)
- **Nothing inferred asserted.** Only stable outcomes: each pack **active**; both humans hold every gate role while
  priya holds none; **Members 3** + the DAG + the enforce→closeout **external** SLA; each flow reaches **3 members /
  closed** with the pega outcome.
- **Membership flakiness absorbed** via `expect.poll` around a PUT+GET-verify (read-after-write). **Fresh pack keys**
  per run dodge the runtime's non-evicting bundle-cache.
- **Folded-in orthogonal checks:** owner-gating (marcus doesn't see the Registry nav), live-SSE (the cohort page
  reflects closed/outcome without a reload).
- **Retains everything** (no teardown) and **skips** on `502 copilot_llm_unavailable`.

## 3. Two clean commands (no flags)
- `bash tools/e2e.sh` → the deterministic gate (fast, green, tears down; copilot spec excluded).
- `bash tools/e2e-copilot.sh` → the copilot lifecycle (own config, no deterministic setup, **no teardown**, retains
  everything; skips without a model). It owns a **distinct** cohort id `ach_copilot_cohort` (never collides with the
  gate's `ach_exposure_cohort`). Re-run needs a clean DB (it retains; a second run finds `ach_copilot_cohort` and
  skips with a "wipe the DB" message).
- Docs updated: `e2e/README.md` + `backend/docs/engineering/running-e2e-tests.md` (two commands, flag docs removed).

## 4. Verification
### Deterministic gate — GREEN
```
$ bash tools/e2e.sh
… ACH domain setup: ach_exposure_cohort/packs onboarded; grants marcus(enforce)/riya(assess+closeout)
✓  ach-lifecycle (6/6): role split distinct · Members 3 · DAG+SLA · credit_approve/Released · debit_reject/Purged · late_closeout external-breach/Released
✓  cohorts · dag-sla-editor · hitl-arc · live-sse · instance-diagram · onboarding(-condition) · owner-gating · _smoke
19 passed (2.7m)
[e2e] teardown: revoked roles; removed cohort definition + ACH packs
✅ e2e: no failures.
```
The copilot spec is **excluded** (0 occurrences in the run); `playwright test --list` confirms it is absent from the
gate and the sole spec under `playwright.copilot.config.ts`.

> **Bring-up note (environmental, not a code issue):** the FIRST gate run on the pre-existing dev stack failed the
> ACH role/flow specs because the stack carried **stray cross-granted roles** from earlier de-risk proofs (marcus
> held the assess+closeout reviewer roles; riya held the enforce role — so all three gate roles resolved to marcus)
> and a **leftover malformed cohort definition**. Neither is touched by this change (onboarding/role logic is
> unchanged). After revoking the stray grants and clearing the runtime bundle-cache (`docker restart
> deploy-agent-runtime-1` — the documented local re-run remedy), the gate is **19 passed**.

### Copilot lifecycle — GREEN (live LLM)
```
$ bash tools/e2e-copilot.sh
✓ 1  priya copilot-onboards the 3 ACH segments; roles distributed; cohort Members 3 + DAG/SLA (2.4m)
✓ 2  credit_approve → 3 members, closed / Released (manual-gate values synthesized from the inferred schema) (32.3s)
✓ 3  debit_reject → 3 members, closed / Purged (32.3s)
✓ 4  late_closeout → enforce→closeout SLA breaches (external), 3 members, still Released (56.0s)
4 passed (4.5m)
✅ copilot e2e: green. Onboarded packs/cohort/instances RETAINED for inspection.
```
The 3 segments onboarded to **active** via the real autopilot (`ach-copilot-{assess,enforce,closeout}-<stamp>`); the
manual enforce/closeout gate values were **synthesized from the copilot-inferred schemas** (no 422); the enforce
4-eyes SoD was cleared by the shared-role picker (marcus authorises, riya provides the second signature). **Retained
state** (verified after the run, nothing torn down):
- 3 active copilot packs + the `ach_copilot_cohort` definition whose DAG nodes are those 3 pack keys;
- 3 closed cohorts: `credit_approve` → **3 / Released**, `debit_reject` → **3 / Purged**, `late_closeout` → **3 /
  Released** with **external SLA breach = 1**.

### No-model skip
When the stack has no copilot model, `onboardSegment` sees the wizard's "isn't reachable right now" (502
`copilot_llm_unavailable`) and the onboarding test calls `test.skip`; the 3 flow tests then skip on the shared
`ready` flag — the whole journey skips with a clear message, never a red.

## 5. Two design fixes found during verification (both now in the spec)
1. **Ordering: cohort definition BEFORE membership.** The registry rejects `PUT …/cohort-membership` with `422
   "unknown cohort definition"` until the def exists (the deterministic `onboard_ach.py` creates the def first; the
   de-risk only "succeeded" because a stale def lingered). The spec now creates the def over the captured pack keys,
   then sets membership.
2. **SoD: share enforce across both humans** (section 2) — the clean exclusive split stalled the credit_approve flow
   at 2 members on the copilot's 4-eyes enforce SoD; granting every gate role to both marcus and riya + the SoD-aware
   picker closes all three flows.

*(Bring-up, environmental — not shipped code: the dev stack's `marcus` had lost his seed roles during earlier
role churn, so with zero roles his post-login nav didn't render and the copilot global-setup login timed out.
Restoring his seed roles (`role.payments.ops_approver` + `role.wire_repair.ops_approver`, per
`identity/app/seeding/seed.py`) fixed it — a clean `down -v` reseed would carry them. The copilot global-setup login
also got a one-retry wrapper for robustness.)*

## 6. Residual fragilities (why the copilot command is non-blocking)
- **Per-run LLM inference varies** — gate role names/counts, human-artifact schemas, and pack structure differ each
  run. The spec reads all of it live, synthesizes gate values from the inferred schemas, and shares roles so a 4-eyes
  SoD is always satisfiable — but a run where the copilot emits a genuinely un-runnable pack (or a 3-way SoD needing
  three distinct approvers, which two humans can't cover) can red the command. Acceptable **because it never gates
  CI** — the deterministic gate does.
- **Retention ⇒ clean-DB re-run.** The command retains everything; a second run without `down -v` skips with a
  "wipe the DB" message. Intentional (inspection-friendly), documented in both e2e docs.
- **Membership read-after-write + non-evicting bundle-cache** — handled (poll + fresh pack keys per run), but they
  are why the copilot path can never be as reproducible as the deterministic gate. Full context:
  `backend/docs/_build-reports/ach_copilot_derisk_findings.md`.

## 7. What was NOT done (by constraint)
No git writes (tree left dirty). No service restarts *from the test*. The copilot run tears **nothing** down. The
deterministic gate's coverage is unchanged and never depends on the LLM.
