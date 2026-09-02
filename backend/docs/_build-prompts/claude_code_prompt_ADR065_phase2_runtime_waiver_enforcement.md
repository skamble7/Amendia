# Claude Code prompt — ADR-065 P2: runtime enforcement of the side-effect gate (agent-runtime)

Second phase of **ADR-065**. P1 (+ its follow-up guard) shipped and is reviewed closed: the waiver exists on the
contract, the registry validates it, and the copilot can no longer let one outlive the binding it justifies. This
phase makes the **agent-runtime** enforce the invariant for the first time. No registry changes (P1 is closed), no
webui (P3), no GLEA (P4). Read
`backend/docs/adr/ADR-065-operator-waivable-human-gate-on-side-effectful-capabilities.md` (Part D and Part E) and
both P1 reports in `backend/docs/_build-reports/` first.

## Why

The runtime currently does **not** enforce the side-effect gate at all. `app/engine/task_runner.py:410-441`
dispatches purely on the manifest's declared `hitl_mode`; the only fail-closed check keys on capability *kind*
(`_is_deep_agent`, :417-422), never on `side_effect`. Until P1 that was tolerable — "ungated side-effect" was an
impossible manifest state, so the registry's activate endpoint was a sufficient single chokepoint.

P1 made it a **legal** state. The runtime must now be able to tell a *legitimately waived* binding from a
mis-built, hand-edited, or out-of-band manifest. Without this, the only thing standing between a hand-written
manifest and an ungated real-world action is a validator the manifest never has to pass twice.

Note the safety property that makes this cheap: **no existing pack can trip the new check.** Before P1 an ungated
side-effectful binding could not be activated, so every pack in the field is either gated or read-only. The check
can only fire on something new.

## Read first

- `app/engine/task_runner.py` — `NodeContext` (:100-140), the dispatch (:410-441) with the `_is_deep_agent`
  fail-closed check (:417-422) as the pattern to mirror, `_side_effect(ctx.descriptor)` (:833-839, already used
  downstream of a gate to synthesize the proposed action), and the human/assist path (:871-874 runs the assist in
  `mode="execute"` **before** the `interrupt()` at :896).
- `app/engine/bundle.py:149-200` (`build_node_contexts`) — where `hitl_mode`/`role` are derived from the manifest
  binding; the waiver is threaded here.
- `app/engine/call_activity.py:93-106` (`_scope_ctx`) — how a `NodeContext` is rebuilt for an inlined callee.
- `app/engine/compiler.py:278-281` (multi-instance host requires `hitl_mode == "none"`) and :189-197 (timer
  boundary refused on a gated **or** side-effectful serviceTask).
- `backend/docs/adr/ADR-030-error-boundary-modeled-rejection-paths.md` and the wire-screen fail-loud fix in
  `compiler.py`'s boundary router — the precedent for Deliverable 4.
- P1's manifest shape: a waived binding serialises as `binding.side_effect_waiver = {"justification": "<text>"}`.

## Deliverable 1 — thread the waiver onto `NodeContext`

`bundle.py::build_node_contexts` reads `binding.side_effect_waiver` off the manifest and puts it on
`NodeContext`. Keep it a **structured value, not a bool** — P4 will add `waived_by` / `waived_at` /
`waived_capability_id` and must not need a `NodeContext` reshape. Read defensively (`getattr` / `.get` with a
`None` default) so a bundle built from an older cached manifest doesn't explode.

## Deliverable 2 — the fail-closed check (the point of this phase)

In the mode-`none` branch of the capability dispatch (`task_runner.py:410-441`), immediately alongside the
existing `_is_deep_agent` check: if `_side_effect(ctx.descriptor) == "side_effectful"` and the node carries **no**
waiver → raise `NodeExecutionError(..., reason="side_effect_ungated")` with a loud, specific message naming the
element and capability. When a waiver **is** present, execute normally and log at INFO that the node ran ungated
under a waiver, including the justification — an ungated real-world action must never be silent in the runtime
log either.

Order matters: check **before** `_produce_outputs(..., mode="execute")`. The whole point is that the tool is never
called.

## Deliverable 3 — the same check on the human-assist path

P1 closed the assist hole at the registry (`assist_side_effect_requires_approve_actions`). The runtime mirror is
still open: `task_runner.py:871-874` runs a human task's `assist_capability` in `mode="execute"` *before* the
`interrupt()`. Note the human executor is routed to `_run_manual` at :411-412, **before** the `hitl_mode`
dispatch, so Deliverable 2's check does not cover it — this needs its own check on the assist descriptor, same
reason code, same fail-closed semantics.

## Deliverable 4 — `side_effect_ungated` must fail LOUD, never be masked

This is the wire-screen lesson and it is not optional. A codeless runtime error caught by a **catch-all error
boundary** (a boundary with no `errorRef`) gets silently re-labelled as a modelled business outcome — that is
exactly how a broken side-effect call once surfaced as a compliance "hold" and cost a long hunt.

`side_effect_ungated` is a **platform integrity failure, not a business error.** It must be excluded from
catch-all boundary routing the same way the codeless `MCP_TOOL_ERROR` fallback already is in the compiler's
boundary router, so it lands in `FAILURE_SINK` with the instance **failed** and a loud log. An explicitly modelled
`errorRef` must not be able to catch it either. **Confirm the existing exclusion mechanism before extending it,
and reuse it rather than adding a parallel one.**

## Deliverable 5 — multi-instance, compiler half (ADR-065 Part E)

P1 added the validator rule `multi_instance_side_effect_unsupported`. Add the compiler counterpart: a
`side_effectful` capability may not be a multi-instance host, **waiver or not** — a `CompilerError`, in the style
of the adjacent refusals at :189-197 and :205-215. Defense in depth for a manifest that did not come through the
registry.

Also **confirm** `compiler.py:189-197` (timer boundary) needs no change — it already keys on `side_effectful`
independently of the gate, so allowing `none` should not have widened it. Say so explicitly in the report; if the
premise is wrong, that is a finding.

## Do not

- Do not change **process-registry**, `libs/amendia_contracts`, the webui, or GLEA. P1 is closed; do not
  "improve" its validation while you are here.
- Do not change the behaviour of **gated** tasks, the HITL ladder, `hitl_rank`, SoD, or the artifact/commit path.
- Do not make the check conditional on `AGENTRT_SIMULATION_MODE`. It is a manifest-legality check, not an
  execution concern — it must hold identically in simulation (which is also where most tests run).
- Do not add config, an env var, or any runtime flag that disables the check. The waiver on the binding is the
  only legitimate way past it.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- **Every existing pack is unaffected** — the seeded packs and the ACH fixture run exactly as before. Prove it,
  and state why it is guaranteed (no activatable pack could contain an ungated side-effect before P1).
- A hand-built manifest with a side-effectful capability at `hitl: none` and **no** waiver → the instance
  **fails** with `side_effect_ungated`; the tool is **never called** (assert on the executor/MCP call, not just on
  the instance state).
- The same manifest **with** a waiver → executes normally, with the justification in the log.
- The same pair on the **human-assist** path (Deliverable 3).
- A catch-all error boundary over the failing node does **not** swallow it — the instance still fails
  (Deliverable 4). This is the assertion that would have caught the wire-screen class of bug.
- A side-effectful multi-instance host → `CompilerError` (Deliverable 5).
- `pytest` green for agent-runtime; process-registry and `libs/amendia_contracts` untouched (prove it). No
  OpenAPI or generated-type change is expected — say so explicitly if that turns out to be wrong.
- **Reviewer note:** not live until `docker compose build agent-runtime` (+ restart). Note also that the runtime
  holds a **non-evicting bundle cache** — a stack that has already loaded a pack will not see re-threaded
  `NodeContext` fields until restart. Call this out for the operator.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR065_phase2_runtime_waiver_enforcement_report.md`
(uncommitted): (1) outcome one-liner; (2) where the waiver is threaded and the exact shape on `NodeContext`;
(3) each enforcement point with its file:line and the reason code; (4) **Deliverable 4 — the boundary-exclusion
mechanism you found and reused, quoted, and proof a catch-all cannot swallow it**; (5) the Deliverable 5
timer-boundary confirmation (or the finding, if refuted); (6) verification — commands and results, including the
"tool never called" assertion and the unaffected-existing-packs proof; (7) anything P3/P4 needs (what the UI
should say when a node fails `side_effect_ungated`; what GLEA should carry).

## Working agreement

No git write commands — leave the tree dirty for Sandeep. agent-runtime only. Mirror the existing
`_is_deep_agent` fail-closed check rather than inventing a new pattern, and reuse the existing catch-all boundary
exclusion rather than building a parallel one. The smallest change that makes the runtime stop trusting the
manifest blindly.
