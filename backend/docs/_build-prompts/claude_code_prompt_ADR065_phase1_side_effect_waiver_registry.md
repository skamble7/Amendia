# Claude Code prompt — ADR-065 P1: the **side-effect waiver** — contracts + registry validation (backend-only)

First phase of **ADR-065**. Make the human gate on a side-effectful capability **default-on but waivable**, per
binding, with a **required written justification**. This phase is **contract model + registry validation only** —
no runtime enforcement (P2/agent-runtime), no webui (P3), no GLEA audit payload or fixture migration (P4). Read
the ADR first: `backend/docs/adr/ADR-065-operator-waivable-human-gate-on-side-effectful-capabilities.md`.

## Why

Today the gate is absolute: `pack_validator.py:301` (`side_effect_requires_approve_actions`) and
`services/onboarding.py:823` (`_check_hitl_guard`) both hard-fail, and there is no flag, env var or override
anywhere. But the gate is *already* removable in practice — by declaring an action tool `read_only`, which the
operator, the copilot's `set_side_effect` mutation, and any headless caller can all do freely. Our own ACH
fixture does exactly that (`e2e/fixtures/onboarding/onboard_ach.py:171-176`). So the real choice is between an
**untraceable** workaround and an **explicit, justified, auditable** one. This phase builds the explicit one and
closes two pre-existing holes in the same rule while we are in stage 4.

## Read first

- `libs/amendia_contracts/amendia_contracts/process_pack.py` — `Hitl` (:126-134), `Binding` (:183-190) and its
  `_executor_matches_kind` validator (:218-219), `HumanExecutor.assist_capability` (:88-92). The waiver goes on
  `Binding`.
- `libs/amendia_contracts/amendia_contracts/capability.py` — `SideEffect` (:44-46), `Constraints.min_hitl_mode`
  (:138-141). **`min_hitl_mode` becomes the non-waivable floor** — do not let the waiver touch it.
- `libs/amendia_contracts/amendia_contracts/common.py:54-84` — `HitlMode`, `_HITL_RANK`, `hitl_mode_at_least`.
  Unchanged; note `approve_actions` and `manual` are rank-equal.
- `backend/services/process-registry/app/validation/pack_validator.py` — `_stage4_hitl_policy` (:287-311), the
  `APPROVE_ACTIONS` constant (:43), the `validate()` call site (:122), and **stages 3 (:277-281) and 5
  (:481-482), which already resolve the assist descriptor** — stage 4 is the one that doesn't look at it.
- `backend/services/process-registry/app/validation/deep_agent.py:54-66` — `deep_agent_requires_hitl` and the
  `deep_agent_justifications` waiver. **This is the shape to follow**, and `deep_agent_requires_hitl` stays
  absolute.
- `backend/services/process-registry/app/validation/report.py:62-78` — `error` / `warning` / `ok`. Note `ok` is
  purely `not has_errors`, so a warning is non-blocking and still surfaces in the report.
- `backend/services/process-registry/app/services/onboarding.py` — `_check_hitl_guard` (:823-834), its call site
  (:733), `_capability_io_and_policy` (:1372-1402) which resolves `(side_effect, floor)`, the error raise (:806),
  the role rule (:709-711), the assemble re-validation (:1161-1175), and the manifest `hitl` composition
  (:1691-1694) — the waiver must survive into the emitted manifest.
- `backend/services/process-registry/app/models/onboarding.py` — `StagedBinding` (:330-350), `BindingInput`
  (:527-545). Both must carry the waiver through the session round-trip.
- `backend/services/process-registry/app/services/copilot/reconcile.py:760-777` (`_clamp_hitl`) — **this clamps
  up unconditionally and would silently destroy a waiver.** See Deliverable 5.
- `backend/services/process-registry/tests/test_pack_validator.py:139-145` and `:355-366`,
  `tests/test_onboarding.py:311-324` — the tests that assert today's absolutism; they will flip.

## Deliverable 1 — the contract (`process_pack.py`)

```yaml
bindings:
  - element_id: Task_NotifyOrchestrator
    executor: { type: capability, capability: "cap.ach.notify_pega@^1.0.0" }
    hitl: { mode: none }
    side_effect_waiver:
      justification: >
        Idempotent status handback to the Pega orchestrator, which is the authority for this case and
        re-confirms receipt. No irreversible effect and no human decision to make.
```

- `SideEffectWaiver` model with **`justification: str`, required, non-empty after strip, minimum 20 characters**
  (a pydantic validator — reject at parse time). **There is no boolean form**: a waiver always carries a reason.
- `Binding.side_effect_waiver: Optional[SideEffectWaiver] = None`. Purely additive — an absent waiver is exactly
  today's behaviour.
- Finalise field names to repo convention but keep the semantics exact.

## Deliverable 2 — stage 4 honours the waiver, and only the waiver's own rule

In `_stage4_hitl_policy`:

- `side_effect_requires_approve_actions` fires **unless** `b.side_effect_waiver` is present. When it is present
  and load-bearing, emit `report.warning("side_effect_waived", ...)` carrying the element id, capability id and
  justification — so an ungated real-world action is never silent in the validation report.
- **`hitl_below_capability_floor` is NOT waivable.** The capability author's `constraints.min_hitl_mode` still
  applies with a waiver present. This is the deliberate promotion in ADR-065 Part B: `min_hitl_mode` is how an
  MCP team marks their own tool's gate non-waivable. Add a test that proves a waiver cannot get past it.
- **`deep_agent_requires_hitl` is NOT waivable** (`validation/deep_agent.py:55-58`) — verify a waiver does not
  reach it, and add a test.
- **Dead waivers are an error.** `side_effect_waiver_not_required` when a waiver is present but the capability is
  `read_only`, or the binding's `hitl.mode` already meets the floor. A waiver must never sit dormant where a
  later capability change would silently activate it.
- Mirror all of the above in `_check_hitl_guard` (`services/onboarding.py:823-834`) so assemble and pack
  validation agree. They must never disagree — the assemble path is what the wizard hits and the validator is
  what activation re-runs.

## Deliverable 3 — close the `assist_capability` hole (ADR-065 Part G)

**Confirm the premise empirically before changing anything.** The claim is that stage 4 resolves a descriptor
only for `ex.type == "capability"` (:287-311), while `agent-runtime/app/engine/task_runner.py:871-874` runs a
human task's `assist_capability` in `mode="execute"` *before* the `interrupt()` at `:896` — so a side-effectful
assist commits its effect un-gated today with no validator finding. Write a failing test first that binds a
`side_effectful` capability as a `HumanExecutor.assist_capability` and shows the pack validates clean. **If the
premise is wrong, say so in the report with the evidence and skip this deliverable** — do not patch around a
hole that isn't there.

If confirmed: stage 4 also resolves the assist descriptor (stages 3 and 5 already show how) and applies the same
rule, under a distinct code `assist_side_effect_requires_approve_actions` so it is distinguishable in a report.
The same waiver on the same binding covers it.

Second, smaller item: a `human` executor bound at `hitl.mode = none` currently passes validation and then raises
at runtime (`allowed_decisions_for("none")`, `agent-runtime/app/engine/engine.py:706`). Add the validation-time
error `hitl_none_on_human_executor`.

## Deliverable 4 — multi-instance stays blocked (ADR-065 Part E, validator half)

Today a side-effectful capability cannot be a multi-instance host, but only **accidentally**: `agent-runtime`'s
`compiler.py:278-281` requires `hitl_mode == "none"` for an MI host, and stage 4 requires `>= approve_actions`
for side-effectful. Allowing `none` dissolves that accident, and one waiver would authorise N real-world actions
from a single decision.

Add an explicit validator rule `multi_instance_side_effect_unsupported`: a `side_effectful` capability may not be
bound to a multi-instance activity, **waiver or not**. Follow the existing style of the adjacent construct rules
(`bpmn_timer_boundary_side_effect_unsupported` :332-338, `bpmn_subprocess_boundary_side_effect_unsupported`
:393-396). The compiler half lands in P2. `compiler.py:189-197` (timer boundary) already keys on
`side_effectful` independently of the gate — confirm it needs no change and say so.

## Deliverable 5 — the copilot may never waive, and must never destroy a waiver

- **No `set_waiver` mutation.** Do not extend `MUTATION_KINDS` (`copilot/mutations.py:42-43`) or the prompt's
  closed vocabulary (`copilot/prompt.py:178-195`). An LLM must not be able to remove a human gate.
- **`_clamp_hitl` (`copilot/reconcile.py:760-777`) must respect an existing waiver.** It currently clamps up to
  the floor unconditionally, so a human-set waiver followed by a copilot chat turn would silently re-gate the
  binding (or worse, half-apply). It must: leave a waived binding's mode alone, never create a waiver, and
  preserve the waiver on any binding it does not otherwise rewrite. Add a test for the wizard-waives →
  copilot-chat-edits → waiver-survives round trip.

## Deliverable 6 — session round-trip and the emitted manifest

`StagedBinding` and `BindingInput` carry `side_effect_waiver`; `set_bindings` accepts and persists it; the
manifest composition at `onboarding.py:1691-1694` emits it. Verify the **pack-edit** round trip
(`POST /onboarding/from-pack/{pack_key}`) rehydrates a waiver from an existing manifest rather than dropping it —
a silently-dropped waiver on re-edit would re-gate a working pack.

## Deliverable 7 — warn on mislabeling (ADR-065 Part H)

Non-blocking `side_effect_downgraded_from_inference` warning when an operator sets `read_only` on a tool whose
introspected output carries the acknowledgement shape (`services/mcp_introspect.py:88-107`, `:321`). Not an
error — the ack-shape inference is a heuristic and can be wrong.

**Put it where the signal actually exists.** `suggested_side_effect` lives on the introspected tool in the
onboarding session, most likely **not** reachable from the pack validator, which sees only the resolved
descriptor. Confirm where it is genuinely in scope and put the warning there. **If it is recoverable at neither
point, say so in the report rather than inventing a signal** — do not persist a new field just to carry it
without flagging that as a deviation.

Related, cheap: a `distinct_actor` SoD policy naming a waived (un-gated) element is meaningless, because an
un-gated step writes no `human` `actor_log` entry (`agent-runtime/app/engine/hitl.py:29-53`). Emit a
`sod_element_ungated` warning.

## Do not

- Do not touch **agent-runtime** (the runtime fail-closed check, `NodeContext`/`bundle.py` threading,
  `call_activity._scope_ctx` propagation and the compiler MI rule are all **P2**), the **webui** feature code
  (**P3**), or the GLEA audit payload and the ACH fixture migration (**P4**). The fixture keeps mislabeling for
  now; that is expected and must not regress.
- Do not change how `side_effect` is inferred, the `HitlMode` ladder, `hitl_rank`, or the runtime behaviour of
  gated tasks.
- Do not make `min_hitl_mode`, `deep_agent_requires_hitl` or `hitl_role_missing` waivable.
- Do not add a boolean or justification-free waiver form anywhere, including the headless API.
- Do not add retroactive waiver of already-active packs — waivers ship with a pack version.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- A pack with **no** waiver validates, assembles, activates and runs exactly as today — every existing seed pack
  (`wire-repair-standard`, `wire-repair-agentic`, `payment-compensation`) still validates clean.
- A `side_effectful` capability bound at `hitl: none` **with** a valid waiver validates clean, assembles, and
  reaches `active`; the validation report carries the `side_effect_waived` warning with the justification.
- **Rejections with clear messages:** waiver with an empty / whitespace / under-length justification (parse-time);
  waiver on a `read_only` capability; waiver on a binding already at `approve_actions`; waiver attempting to get
  past `min_hitl_mode`; waiver on a `deep_agent`; `side_effectful` bound to a multi-instance host with a waiver;
  `human` executor at `hitl: none`; and — if Deliverable 3's premise is confirmed — a `side_effectful`
  `assist_capability` with no gate and no waiver.
- The waiver survives: `set_bindings` → session → assemble → emitted manifest → `from-pack` re-edit → copilot
  chat turn.
- `pytest` green for **process-registry** and **agent-runtime** (the latter must be untouched — prove it), plus
  `libs/amendia_contracts`. The tests at `test_pack_validator.py:139-145`, `:355-366` and
  `test_onboarding.py:311-324` assert today's absolutism and will need flipping — flip them to assert
  "blocked **without** a waiver, allowed **with** one", do not delete them.
- **OpenAPI snapshot re-dumped** and `webui/src/api/gen/registry.ts` regenerated so `tsc` / `npm run build` stay
  green. The webui does not yet *use* the field (that's P3), but the generated types must compile.
- **Reviewer note:** none of this is live until `docker compose build process-registry` (+ restart).

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR065_phase1_side_effect_waiver_registry_report.md`
(uncommitted): (1) outcome one-liner; (2) the contract addition (final field names, the justification rule) and
every finding code added, with severity; (3) **Deliverable 3 — state plainly whether the `assist_capability`
hole was confirmed or refuted, and quote the evidence**; (4) where Deliverable 7's inference signal turned out to
be reachable, and any deviation; (5) what was deliberately left for P2/P3/P4; (6) verification — exact `pytest` /
snapshot-dump / `gen:api` / build commands and results, including each rejection case by name, plus proof the
seed packs still validate; (7) follow-ups and anything P2 needs to know (specifically: what shape the waiver
takes on the manifest, so `bundle.py` can thread it onto `NodeContext`). One screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Backend-only: `libs/amendia_contracts` +
`process-registry`. Follow the `deep_agent_justifications` precedent for shape and the adjacent stage-4 construct
rules for style. The waiver is **additive and optional** — zero behaviour change when it is absent. Confirm
Deliverable 3's premise empirically before patching it; a well-evidenced "the premise is unsupported" is a better
outcome than a speculative fix.
