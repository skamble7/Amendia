# Claude Code prompt — ADR-065 correction: a side-effectful assist is un-gated by construction

Small cross-cutting correction between **ADR-065 P2** (shipped, reviewed) and **P3**. P1 and P2 are otherwise
accepted. This fixes **one rule that was stated wrongly in the ADR** and therefore implemented wrongly in both
services. Read the amended **Part G** of
`backend/docs/adr/ADR-065-operator-waivable-human-gate-on-side-effectful-capabilities.md` first — it now carries
a dated revision explaining the correction.

## Why

Part G originally said the assist path is subject to "the same rule and the same waiver" as the capability path.
Both implementations faithfully followed that, keying on the HITL rank ladder:

- registry: `assist_side_effect_requires_approve_actions` — fires when the assist is `side_effectful` **and**
  `hitl < approve_actions`.
- runtime: `_run_manual` (`app/engine/task_runner.py`) — same condition before running the assist.

But `_HITL_RANK` scores **`MANUAL` and `APPROVE_ACTIONS` equally at 2**
(`libs/amendia_contracts/amendia_contracts/common.py:64-84`). So `hitl_mode_at_least("manual",
"approve_actions")` is `True`, the check is skipped, and a human task at **`manual`** — the normal mode for a
human executor, and the mode P1 used to fix the seven broken human-task tests — runs a side-effectful assist with
no waiver and **no human having seen the task**. The assist executes at `mode="execute"` *before* the
`interrupt()`.

The ladder encodes **how much authorization a task carries, not ordering.** For a capability executor at
`approve_actions` the semantics are propose → gate → execute, so rank 2 really does mean the effect follows the
authorization. On the assist path the effect **always precedes the interrupt**, whatever the mode — so no rank
buys anything.

**The corrected rule: a side-effectful `assist_capability` is un-gated by construction and ALWAYS requires an
explicit waiver, regardless of the human task's `hitl.mode`.**

## Deliverable 1 — registry: drop the rank clause from the assist rule

`backend/services/process-registry/app/validation/pack_validator.py` (stage 4) and its mirror in
`app/services/onboarding.py::_check_hitl_guard`: `assist_side_effect_requires_approve_actions` fires whenever the
resolved **assist** descriptor is `side_effectful` and the binding carries no waiver — **with no HITL-mode
condition at all**. Update the message so it says why (the assist runs before the gate), and consider whether the
code name still reads true now that `approve_actions` does not clear it; rename only if it actively misleads, and
say so in the report.

**Leave the capability rule exactly as it is.** `side_effect_requires_approve_actions` keeps its rank comparison.
Only the assist rule changes.

## Deliverable 2 — the dead-waiver interaction (do not miss this)

`side_effect_waiver_not_required` currently fires when the binding's `hitl.mode` already meets the floor. Under
the corrected rule that is **wrong** for a binding whose assist is side-effectful: a human task at `manual` with a
side-effectful assist now *needs* its waiver, and the dead-waiver rule would reject the very pack the new rule
requires a waiver for — an unfixable pack, rejected whichever way the operator turns.

A waiver is dead only when **neither** the executor **nor** the assist needs it. Implement that, and test the
specific combination: `manual` human task + side-effectful assist + waiver → **validates clean** (with the
`side_effect_waived` warning), not `side_effect_waiver_not_required`.

## Deliverable 3 — runtime: the same correction

`backend/services/agent-runtime/app/engine/task_runner.py::_run_manual` — drop the
`hitl_mode_at_least(ctx.hitl_mode, "approve_actions")` clause so the check fires on any side-effectful assist
without a waiver. Keep everything else P2 shipped: same `side_effect_ungated` reason code, same fail-closed
placement before the assist runs, same INFO log of the justification when waived.

## Deliverable 4 — find out what this newly rejects

The corrected rule is stricter, so a pack with a side-effectful assist on a task at `manual` / `approve_actions`
that validated yesterday will now need a waiver. **Establish empirically whether any exist** — search the seed
packs (`backend/services/agent-runtime/seed/**`), the e2e fixtures (`e2e/fixtures/**`), the smoke scenarios, and
the test manifests for a `human` executor carrying an `assist_capability`, and check each assist's `side_effect`.

Report the finding either way. My expectation is **none** — assists are normally read-only drafting helpers — but
that is a prediction, not a result. If any exist, do **not** silently add a waiver: list them in the report and
stop, so the right call (waiver vs. making the assist read-only) is made deliberately.

## Do not

- Do not change the **capability**-path rule, the HITL ladder, `_HITL_RANK`, or `hitl_mode_at_least`. The ladder
  is correct for what it models; it was simply the wrong instrument for the assist path.
- Do not touch the webui (P3), GLEA (P4), the waiver contract, or the copilot guard.
- Do not weaken any P1/P2 test to accommodate the stricter rule — a test that now fails is either a fixture that
  legitimately needs a waiver (add one, deliberately, and say so) or a genuine regression.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- Registry: `manual` human task + side-effectful assist + **no** waiver → error; **with** a waiver → clean, plus
  the `side_effect_waived` warning and **no** `side_effect_waiver_not_required` (Deliverable 2).
- Registry: the capability-path rule is provably unchanged — a side-effectful *executor* at `approve_actions`
  still validates clean with no waiver.
- Runtime: `manual` + side-effectful assist + no waiver → instance fails `side_effect_ungated`, and **the assist
  tool is never called** (assert on the executor spy, as P2 did); with a waiver → runs, justification logged.
- Deliverable 4's survey reported, with any hits listed rather than fixed.
- `pytest` green for process-registry, agent-runtime and `libs/amendia_contracts`. No contract, OpenAPI or
  generated-type change is expected — say so explicitly if that turns out to be wrong.
- **Reviewer note:** live only after `docker compose build process-registry agent-runtime` **and a restart** (the
  runtime's non-evicting bundle cache).

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR065_assist_gate_ordering_fix_report.md` (uncommitted):
(1) outcome one-liner; (2) the corrected condition in each of the three places, quoted; (3) how the dead-waiver
rule now decides load-bearingness; (4) **Deliverable 4's survey result — what carries a side-effectful assist
today, or a clear "none found" with the search you ran**; (5) whether you renamed the finding code and why;
(6) verification — commands, results, and the tool-never-called assertion. Half a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Two services, one condition each, plus the dead-waiver
interaction. The smallest change that makes the assist rule say what Part G now says. If Deliverable 4 turns up
packs that would newly fail, stop and report rather than papering over them with waivers nobody chose.
