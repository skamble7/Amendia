# ACH copilot single-test — de-risk findings (scope decision pending)

**Status:** de-risk complete, **no production e2e files changed**. The original task (collapse the whole
Playwright suite into ONE copilot-driven `ach-lifecycle.spec.ts` and delete the deterministic path) was paused after
de-risking revealed enough irreducible fragility that deleting the green suite is a real trade-off worth deciding
deliberately. This report is the evidence for that decision.

All findings below were established empirically against the live local stack (registry 18084, runtime 18083,
identity 18086, glea 18090, keycloak 8087, pega_stub 9095, MCPs 8075/8076/8077) using throwaway API proof scripts
(now cleaned up; all `achx-*`/`ach-copilot-*` proof packs + the proof cohort def were deleted, registry left empty of
proof artifacts).

---

## What the task asked for

One spec, `e2e/tests/ach-lifecycle.spec.ts`, that (as priya, via the real-LLM `/registry/onboard` autopilot):
onboards the 3 ACH segments, sets cohort membership, grants gate roles read from the packs, creates the cohort with
the `assess→enforce→closeout` DAG + arrival SLA, runs 3 pega_stub scenarios driving gates through the Task Inbox, and
asserts each cohort reaches MEMBERS=3 and closes. Delete all `--flag`/env paths, the deterministic
`onboard_ach.py`/`ensureAchDomain` setup, the throwaway `copilot-onboarding.spec.ts`, and 9 redundant specs; fold
their orthogonal checks in as inline assertions. Skip on `502 copilot_llm_unavailable`. Retain everything, no
teardown.

---

## ✅ What is proven viable

1. **Copilot onboarding is reliable.** `POST /onboarding/copilot/generate` (real Bedrock LLM via
   `dev.llm.bedrock.explicit-creds`, resolved through config-forge :18040) returns a validator-clean assembled draft
   in ~16 s/segment; `POST /onboarding/{sid}/commit` publishes an **active** pack. Confirmed across multiple runs for
   all three segments (assess/enforce/closeout) against the corpus BPMNs + trigger schemas in
   `backend/docs/methodology/worked-examples/ach_exposure/`.

2. **The cohort forms with copilot packs and the pega handback chain fires.** With fresh pack names and membership
   persisted **before the first dispatch**, a `credit_approve` case joined the cohort and advanced
   `__start__→assess→enforce`: proof showed `members=2 rollup={done:1, running:1}` with assess handed back (its
   `notify_pega` gate driven) and enforce running. The A→B handback is real, not simulated.

3. **The runtime enforces gate role at claim** (`403 caller lacks required role`) — so reading the gate role from the
   onboarded pack and granting it to a real persona is both necessary and sufficient to drive a gate. (This corrects
   an earlier "runtime is role-agnostic" assumption.)

---

## ⚠️ Irreducible fragility (the reason to pause)

Each of these is *solvable* with defensive runtime logic, but together they make the single copilot test materially
more complex and inherently more brittle than a deterministic one — because it depends on the LLM producing, on every
run, not just a runnable pack but one whose inferred **schemas and role structure** the test can satisfy.

1. **Human-gate artifact schemas are LLM-inferred → gate values cannot be hard-coded.**
   The final proof got A→B, then `Task_AuthorizeRelease` (a `manual` gate) returned **HTTP 422** on `.../decide`:
   the copilot invented its own `art.achx_enforce_59902.release_authorization` schema, which the corpus-shaped value
   I supplied (`{authorized, case_id, company, decision:{}, records:[]}`) does not satisfy. A copilot test must, at
   runtime, **read each gate's inferred output-artifact schema and synthesize a conforming value** — for every manual
   gate in all three segments. This is the single biggest added complexity.

2. **Inference varies run-to-run.** Observed across runs:
   - enforce gate roles = `{release_approver, purge_approver, orchestration_supervisor}` in one run,
     `{release_approver, purge_approver}` in another.
   - enforce SoD sometimes includes a `distinct_actor` 4-eyes pairing (e.g. PrepareRelease vs AuthorizeRelease) that
     would SoD-exclude a single approver and stall the segment; other runs don't.
   The test must therefore read **roles and SoD** dynamically from the packs and drive with a SoD-aware picker (the
   agreed "grant every gate role to both Marcus and Riya, pick first non-excluded holder" model handles this, but it
   means the clean "enforce→Marcus, assess/closeout→Riya" split is gone).

3. **Cohort-membership PUT is read-after-write flaky.** `PUT /packs/{key}/1.0.0/cohort-membership` returns 200 but
   the value is not always immediately readable back right after commit; a **12× PUT-then-GET-verify** loop was
   required to reliably persist it.

4. **The runtime bundle-cache never evicts.** `load_bundle` caches `(pack_key, version)` — including
   `cohort_membership` — at first dispatch and never refreshes. If any case is dispatched before membership lands,
   that pack is cached membership-less forever and never joins the cohort. Practically this forces **brand-new pack
   names on every run** (or a fully clean stack), and membership must be verified *before* the first case is fired.
   This was the root cause of every earlier "cohort didn't form (members=None)" failure.

---

## The recipe that works (if we build the copilot test)

Confirmed-viable sequence, for the record:
1. Onboard each segment via copilot (generate → commit); **fresh pack names each run** (never previously loaded).
2. `PUT` cohort-membership with a **12× retry+GET-verify** loop **before firing any case**.
3. Read each segment's gate **roles + SoD** from `GET /packs/{key}/1.0.0` bindings; grant all gate roles to both
   Marcus and Riya (post-onboard, no restart).
4. Create the cohort def (delete any stale def first — a stale def pins old pack-keys as DAG nodes).
5. Fire pega_stub scenarios; drive each open HITL task as the **first non-SoD-excluded** role-holder; **for manual
   gates, read the inferred output-artifact schema and synthesize a conforming edit value** (the piece not yet built —
   the 422 above is exactly this gap).
6. Poll GLEA `cohorts/by-correlation/{case}` until `{members:3, done:3, running:0, closed}` + expected outcome.

Open technical gap: step 5's schema-read-and-synthesize was not completed — the proof 422'd at the first manual
enforce gate. Everything before it (onboard → membership → cohort → A→B handback) is proven.

---

## Options on the table (from the scope question)

- **Hybrid (keep + add):** retain the deterministic 19-test suite as the reliable CI baseline; add the copilot ACH
  test as a *separate* spec that skips on `502 copilot_llm_unavailable`. Proves the real-LLM path without betting CI
  green on per-run LLM inference. (My recommendation given the above.)
- **Full replacement (original task):** single copilot spec as the only test; delete the deterministic suite, flags,
  fixtures, and 9 redundant specs. Faithful to the prompt; accepts that a bad LLM run = red CI with no fallback, and
  requires building the runtime artifact-schema synthesis (item 5).
- **Pause & rethink (chosen):** this report; no files deleted, no rewrite.

---

## State of the tree right now

- **No production e2e files modified.** The deterministic suite (`onboard_ach.py`, `global-setup.ts` `ensureAchDomain`,
  all specs, `tools/e2e.sh` flags) is intact and, per the prior correction report, green (19 passed).
- Proof scripts live only under the session scratchpad; all `achx-*`/`ach-copilot-*` proof packs and the proof cohort
  def were deleted from the registry.
- No services were restarted; nothing was torn down that belongs to the real suite.
