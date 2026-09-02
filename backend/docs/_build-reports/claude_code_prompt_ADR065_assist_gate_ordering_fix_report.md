# ADR-065 correction — a side-effectful assist is un-gated by construction

**Outcome: DONE and green.** The assist rule no longer keys on the HITL rank ladder. Because the assist runs at
`mode="execute"` *before* the `interrupt()`, no HITL mode gates it — so a side-effectful `assist_capability` now
**always** requires an explicit waiver, in the registry (validate + assemble pre-check) and the runtime, whatever
the human task's `hitl.mode`. The capability-executor rule is untouched. No contract / OpenAPI / generated-type /
webui / GLEA / copilot change. Tree left dirty.

## The corrected condition, in each of the three places

Previously each site asked "side-effectful assist **and** `hitl < approve_actions`", which — since `_HITL_RANK`
scores `manual == approve_actions == 2` — skipped the check for a human task at `manual` (the normal mode). Now:

1. **Registry validate** — `pack_validator.py:344` (the per-subject loop; `is_assist` distinguishes the two):
   ```python
   needs_waiver = is_se if is_assist else (is_se and not hitl_mode_at_least(mode, APPROVE_ACTIONS))
   ```
   The assist branch dropped the rank term entirely; the capability branch kept it verbatim.

2. **Registry assemble pre-check** — `onboarding.py::set_bindings:761` (human branch):
   ```python
   if assist_se == "side_effectful" and getattr(b, "side_effect_waiver", None) is None:
   ```
   (was `assist_se == "side_effectful" and not hitl_mode_at_least(b.hitl_mode, _APPROVE_ACTIONS)`.) The capability
   mirror `_check_hitl_guard` is unchanged.

3. **Runtime** — `task_runner.py::_run_manual:896`, before the assist runs in `mode="execute"`:
   ```python
   if _side_effect(ctx.assist_descriptor) == "side_effectful":
       waiver = getattr(ctx, "side_effect_waiver", None)
       if waiver is None:
           raise NodeExecutionError(..., reason="side_effect_ungated")
   ```
   (was gated by `and not hitl_mode_at_least(ctx.hitl_mode, "approve_actions")`.) Same reason code, same
   fail-closed placement, same INFO log of the justification when waived, as P2 shipped. The now-unused
   `hitl_mode_at_least` import was removed.

## How the dead-waiver rule now decides load-bearingness (Deliverable 2)

`side_effect_waiver_not_required` fires only when the waiver is **not load-bearing**, and load-bearingness is
computed per subject with the corrected condition above: `waiver_load_bearing = True` when a capability executor
is side-effectful-and-below-floor **or** when an assist is side-effectful (any mode). So a `manual` human task
with a side-effectful assist + waiver is load-bearing → it takes the `side_effect_waived` warning path
(`pack_validator.py:372`), **not** the dead-waiver error (`:378`). Without this, the new rule and the old
dead-waiver rule would have deadlocked that pack — required a waiver and rejected it as dead. Proven by
`test_assist_side_effect_at_manual_requires_waiver_and_waiver_clears`: at `manual`, no waiver → error; with
waiver → clean, `side_effect_waived` present, `side_effect_waiver_not_required` absent.

## Deliverable 4 — what this newly rejects: NONE FOUND

Searched every pack and fixture for a `human` executor carrying an `assist_capability`, then checked each assist's
`side_effect`:
- `rg -rn '"assist_capability"' --glob '*.json' backend/ e2e/` → **two hits**, both `cap.payment.draft_rfi@^1.0.0`,
  on `Task_ObtainInfo` (human, `hitl: manual`) in `seed/wire-repair-standard` and `seed/wire-repair-agentic`.
- `cap.payment.draft_rfi` is **`read_only`** in both packs' `capabilities/`.
- Broadened to `*.yaml`/`*.yml` and to agent-runtime/process-registry test fixtures and `e2e/` — no other assist
  anywhere.

So the only assist in existence is read-only and is unaffected. **The stricter rule newly rejects nothing** —
matching the prediction. No waiver was added anywhere (there was nothing to add one to).

## Did I rename the finding code? Yes.

`assist_side_effect_requires_approve_actions → assist_side_effect_requires_waiver`. Under the correction
`approve_actions` no longer clears the rule (a waiver is required at every mode), so the old name named a
threshold that no longer exists — it *actively* misled. The rename is confined to backend finding-code strings
(`pack_validator.py`, its two test assertions, and comment references in the runtime + P2 test); finding codes are
free-form strings in the validation report, not part of any OpenAPI schema, so there is no contract/generated-type
impact. The capability code `side_effect_requires_approve_actions` is unchanged (its threshold still holds).

## Verification

`uv run --extra dev pytest` (registry, agent-runtime); `uv run --with pytest pytest` (contracts):

| Suite | Result |
|---|---|
| process-registry | **422 passed** (assist test rewritten to the `manual` case + Deliverable 2; net count unchanged) |
| agent-runtime | **402 passed, 4 skipped** (was 405 collected → 406; the P2 "adequately gated is unaffected" test — which encoded the old, buggy assumption — was replaced by two tests asserting the corrected behavior at `manual`) |
| `libs/amendia_contracts` | **9 passed** (untouched) |

**Acceptance checks:**
- Registry: `manual` + side-effectful assist, no waiver → `assist_side_effect_requires_waiver`; with waiver →
  clean + `side_effect_waived`, no `side_effect_waiver_not_required`.
- Registry capability path provably unchanged: `test_side_effectful_at_review_after` /
  `test_waiver_on_already_gated_is_dead` still green — a side-effectful *executor* at `approve_actions` validates
  clean with no waiver.
- Runtime: `test_assist_side_effectful_at_manual_still_requires_waiver_tool_never_called` — `manual` + side-effectful
  assist + no waiver → `NodeExecutionError(reason="side_effect_ungated")` with **`spy.calls == 0`** (the assist
  tool is never called); `test_assist_side_effectful_at_manual_with_waiver_runs` — with a waiver the assist runs
  (`spy.calls == 1`) and the justification is logged.
- **No contract, OpenAPI, or generated-type change** — confirmed; the `M` on `process_pack.py` /
  `webui/openapi/registry.json` / `registry.ts` is P1's additive field, untouched by this correction.

**Reviewer note:** live only after `docker compose build process-registry agent-runtime` **and a restart** (the
runtime's non-evicting bundle cache).
