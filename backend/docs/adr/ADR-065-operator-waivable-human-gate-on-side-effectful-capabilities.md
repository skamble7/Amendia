# ADR-065 — Operator-waivable human gate on side-effectful capabilities (default-on, per-binding, justified)

**Status:** Proposed — 2026-08-28
**Implementation status (2026-09-01):** **P1, the rebind guard, P2, the assist-ordering correction, P3, P4a and P4b are all implemented and reviewed against the diff** — contract, registry validation, runtime fail-closed enforcement, operator UI, provenance + capability bond, and the audit payload. Every suite is green. **Nothing has been verified on a running stack**: no phase could be, and the browser e2e (`tools/e2e.sh`) needs a live compose stack. Status stays *Proposed* until a live pass — waive a step as priya, watch it run un-gated, and find it in the audit store — is done on rebuilt images.
**Revision — 2026-09-01:** **Part G is amended.** The
assist rule originally read "the same rule and the same waiver", which implemented as a rank comparison and
left the common `manual` case un-checked. Corrected below; see § Part G.
**Date:** 2026-08-28
**Context owner:** Sandeep Kamble
**Relates:** ADR-011 (agent-runtime execution; HITL via LangGraph `interrupt`/`resume`), ADR-021 (deep_agent —
never un-gated; `deep_agent_justifications`, the precedent this ADR follows), ADR-024 (self-descriptive MCP
runtime), ADR-036 (multi-instance activities), ADR-052 (business-facing onboarding; the ack-shape side-effect
inference), ADR-055 (deterministic four-eyes; the copilot clamps rather than decides), ADR-060 (pack-owned
capabilities — a descriptor is owned per pack version), ADR-061 (owner-only pack mutations). Methodology:
`backend/docs/methodology/amendia_mcp_implementor_guideline.md` §4 (the acknowledgement-shape convention).

## Context

Amendia enforces one invariant above all others: **a capability that has a real-world effect is executed only
after a human authorises it.** It is the platform's core trust claim, repeated across ADR-021/031/055 and the
MCP implementor guideline.

Today that invariant is absolute and un-overridable. Three enforcement points, all in `process-registry`, all
blocking:

- `validation/pack_validator.py:301` — stage 4, `side_effect_requires_approve_actions`, a `report.error` so the
  pack can never reach `validated`.
- `services/onboarding.py:823` (`_check_hitl_guard`) — 422 `bindings_invalid` at assemble time.
- `routers/packs.py:132-138` — activation re-runs the full validator ("defense in depth"), so even a
  previously-validated pack is re-checked on the way to `active`.

Supporting behaviour: the copilot **clamps up** to the floor rather than rejecting (`copilot/reconcile.py:760-777`),
and the wizard renders weaker modes as `disabled` (`webui/.../OnboardingWizard.tsx:1657`). A search for a policy
flag, env var, `force`/`override`/`waive`/`acknowledge` parameter, or a waiver field on `ValidationReport`
returns nothing: **there is no escape hatch of any kind.**

Two facts make that absolutism less safe than it looks.

**1. Some processes legitimately have no human in them.** A fully-automated handback, a notification, an
idempotent status write to an external orchestrator — these have a real-world effect but no meaningful human
decision, and forcing a gate onto them either blocks the process from being onboarded at all or trains operators
to route around the rule.

**2. Operators already route around it, invisibly.** `side_effect` is **not** transmitted by MCP. Amendia infers
it from whether the tool's output schema carries the acknowledgement shape (`services/mcp_introspect.py:88-107`,
`:321`), and that inference is then freely editable — by the operator in the wizard
(`OnboardingWizard.tsx:956-959`), by the copilot's `set_side_effect` mutation (`copilot/mutations.py:296-298`,
with no restriction on downgrading), and by any headless caller (`models/onboarding.py:474`,
`CapabilityInput.side_effect` defaults `"read_only"`). Our own ACH e2e fixture does exactly this —
`e2e/fixtures/onboarding/onboard_ach.py:171-176` declares `notify_pega` `read_only` in the segments where the
pack does not gate it, *specifically so the guard does not fire.*

So the gate is already removable today. It is removed by **lying about the capability**, which leaves no record
that a gate was consciously dropped, no justification, and nothing an auditor can query. An explicit, recorded,
justified waiver is strictly safer than the status quo — it converts an untraceable workaround into a
first-class, auditable decision.

**3. The runtime does not enforce the invariant at all.** `agent-runtime/app/engine/task_runner.py:410-441`
dispatches purely on the manifest's declared `hitl_mode`; the only fail-closed runtime check keys on capability
*kind* (`deep_agent`), never on `side_effect`. The registry activate endpoint is the single chokepoint. That is
tolerable while "ungated side-effect" is an impossible manifest state. It stops being tolerable the moment it
becomes a legal one.

## Decision

Introduce a **per-binding side-effect waiver**: the gate stays on by default, and the person onboarding the
process may explicitly waive it for a specific task, with a **required written justification**, recorded in the
manifest and the audit trail. The waiver may take the binding all the way to `hitl.mode = none` (fully
autonomous) — that is the point of the feature.

### Part A — The waiver, on the binding

A new optional block on `Binding` (`libs/amendia_contracts/.../process_pack.py`):

```yaml
bindings:
  - element_id: Task_NotifyOrchestrator
    executor: { type: capability, capability: "cap.ach.notify_pega@^1.0.0" }
    hitl: { mode: none }
    side_effect_waiver:
      justification: >
        Idempotent status handback to the Pega orchestrator, which is the authority for this case and
        re-confirms receipt. No irreversible effect and no human decision to make. Reviewed by Payments Ops.
```

- **Per-binding**, not per-capability and not per-pack: the same capability may be gated on one task and waived
  on another, and the decision is scoped to one element in one pack version.
- **`justification` is required and non-trivial** (non-empty after strip, minimum length enforced by the model).
  A waiver with no reason is rejected at the contract level — there is no boolean form.
- **Immutable with the pack version.** Per ADR-060 the manifest is owned by `(pack_key, pack_version)`; changing
  a waiver means a new pack version, exactly like any other binding change.
- Present **only** when it is doing work: a waiver on a binding whose capability is `read_only`, or whose
  `hitl.mode` already meets the floor, is a validation **error** (`side_effect_waiver_not_required`) — dead
  waivers must not accumulate where a later capability change would silently activate them.

### Part B — What a waiver waives, and what it never waives  **[confirm]**

The waiver waives **exactly one rule**: the platform's `side_effectful ⇒ hitl >= approve_actions` floor. It
does **not** waive:

- **`capability.constraints.min_hitl_mode`** — the *capability author's* declared floor
  (`hitl_below_capability_floor`). This is a deliberate promotion: `min_hitl_mode` becomes the mechanism by
  which the team that builds an MCP tool declares a gate **non-waivable**. A bank's MCP team marks
  `execute_payment` with `min_hitl_mode: approve_actions` and no process owner can waive it; `notify_pega`,
  declaring no floor, remains waivable. The capability author gets the last word on their own tool.
- **`deep_agent_requires_hitl`** (ADR-021, `validation/deep_agent.py:54-58`). A deep agent is never un-gated,
  waiver or not.
- **`hitl_role_missing`** and every other stage-4 rule.

### Part C — Only a human may waive; the copilot may not  **[confirm]**

A waiver is a deliberate human act. `copilot/reconcile.py::_clamp_hitl` continues to clamp **up** to the floor
unconditionally, and no `set_waiver` mutation is added to the copilot's closed mutation vocabulary
(`copilot/prompt.py:178-195`, `copilot/mutations.py:42-43`). An LLM must never be able to remove a human gate.

The waiver is set in the wizard, on the Bindings step. Registry mutations are already `role.process.owner`-gated
(ADR-061), so the waiver is inherently owner-only; no new authorization surface is introduced.

### Part D — The runtime becomes a second enforcement point (fail-closed)

Because "ungated side-effect" becomes a legal manifest state, the runtime must be able to distinguish a
*legitimately waived* binding from a mis-built or tampered manifest. It currently cannot.

- `engine/bundle.py:149-200` (`build_node_contexts`) threads the waiver onto `NodeContext`
  (`task_runner.py:100-140`).
- `task_runner.py:410-441`, the mode-`none` branch: if the descriptor is `side_effectful` and the node carries
  no waiver → `NodeExecutionError(reason="side_effect_ungated")`. This is the exact sibling of the existing
  `_is_deep_agent` fail-closed check at `:417-422`.
- `engine/call_activity.py:93-106` (`_scope_ctx`) propagates the waiver into inlined callees — otherwise a
  callee's gate silently vanishes on composition, which is the worst possible failure mode for this feature.

### Part E — Multi-instance fan-out stays blocked  **[confirm — the sharpest consequence]**

Today `compiler.py:278-281` requires `hitl_mode == "none"` for a multi-instance host, and stage 4 requires
`>= approve_actions` for anything side-effectful. Those two rules **accidentally** make a side-effectful
capability structurally incapable of being a multi-instance host. Allowing `none` removes that accident, and a
side-effectful capability would silently become eligible for **un-gated N-way fan-out**.

**Decision: keep it blocked, explicitly.** Add a rule — validator and compiler — refusing a `side_effectful`
capability as a multi-instance host regardless of waiver. Waiving a gate on one deliberate action is a
different risk from authorising an unbounded number of them from one decision. If fan-out of real-world actions
is ever wanted, it gets its own ADR.

`compiler.py:189-197` (timer boundary refused on a gated **or** side-effectful serviceTask) already keys on
`side_effectful` independently of the gate, so it is unaffected.

### Part F — Visibility: a waiver must be loud

An ungated real-world action is the highest-risk thing a pack can contain. It must be the *most* visible thing,
not the least. Today it would be the least: `webui/src/features/copilot/humanize.ts:46-58` filters
`hitl_mode !== "none"`, so an ungated step disappears entirely from the review summary
(`CopilotReview.tsx`, `CopilotSteppedReview.tsx`).

- **Review summary** — waived bindings render as a distinct, prominent risk row ("runs without human approval"),
  with the justification, never omitted.
- **Pack detail** — waivers listed on the pack's page alongside the capability and the justification.
- **GLEA** — the pack-publish audit event carries the waiver set (element_id, capability_id, justification, the
  owner who published). An auditor must be able to answer *"which live packs perform real-world actions with no
  human in the loop, and why?"* from the audit store alone. This is the compliance payoff that makes the feature
  net-positive for governance rather than a hole in it.

### Part G — Close the pre-existing `assist_capability` hole

Stage 4 resolves a descriptor only for `ex.type == "capability"` (`pack_validator.py:287-311`), so a
**`human` executor's `assist_capability` is never side-effect-checked** — while `task_runner.py:871-874` runs
that assist in `mode="execute"` *before* the `interrupt()` at `:896`. A side-effectful capability bound as a
human task's assist therefore commits its side effect un-gated **today**, with no validator finding. Stage 3
(`:277-281`) and stage 5 (`:481-482`) already resolve the assist descriptor; stage 4 simply does not look at it.

Fixed here, in the same stage, because building an explicit, justified door beside an unlocked window is
incoherent.

**The assist rule is NOT the capability rule (amended 2026-09-01).** Stating it as "the same rule" produced an
implementation keyed on the HITL rank ladder — `side_effectful assist AND hitl < approve_actions` — and
`_HITL_RANK` scores **`manual` and `approve_actions` equally (2)**. So a human task at `manual`, the *normal*
mode for a human executor, skipped the check entirely and ran a side-effectful assist ungated.

The ladder encodes **how much authorization a task carries, not ordering.** For a capability executor at
`approve_actions` the semantics are propose → gate → execute, so rank 2 genuinely means the effect follows the
authorization. On the assist path the effect **always precedes the `interrupt()`**, whatever the task's own mode
— so no rank buys anything there.

**Therefore: a side-effectful `assist_capability` is un-gated by construction and ALWAYS requires an explicit
waiver, regardless of the human task's `hitl.mode`.** The rank comparison is dropped from the assist rule (it
stays, unchanged, on the capability rule).

Consequence for the dead-waiver rule: a waiver on a binding whose *executor* gate already meets the floor is
**not** dead if that binding's *assist* is side-effectful — it is the only thing authorising the assist. A waiver
is dead only when neither the executor nor the assist needs it.

Also folded in: a `human` executor bound at `hitl: none` currently passes validation and then raises at runtime
(`allowed_decisions_for("none")`, `engine.py:706`) — add the validation-time error.

### Part H — Retire the mislabeling workaround  **[confirm]**

With a legitimate waiver available, declaring an action tool `read_only` to dodge the guard has no honest
motive. Add a non-blocking **warning** (`side_effect_downgraded_from_inference`) when an operator sets
`read_only` on a tool whose output carries the acknowledgement shape, so the choice is visible in the validation
report. Not an error — the inference is a heuristic and can be wrong.

`e2e/fixtures/onboarding/onboard_ach.py:171-176` is migrated to use a waiver instead of mislabeling, which makes
the fixture an honest demonstration of the new feature.

## Phases (backend before frontend, each independently testable)

- **P1 — contracts + registry.** `side_effect_waiver` on `Binding`; `BindingInput`/`StagedBinding` carry it
  through the session; stage 4 and `_check_hitl_guard` honour it; Part B floors stay absolute; Part G assist +
  human-mode fixes; Part E validator rule; Part H warning.
- **P2 — runtime.** `NodeContext` + `bundle.py` threading; the mode-`none` fail-closed check;
  `call_activity._scope_ctx` propagation; Part E compiler rule.
- **P3 — webui.** The Bindings-step waiver affordance (a required justification textarea, never a bare
  checkbox); `humanize.ts` visibility fix; pack-detail rendering; regenerated API types. **Decided 2026-09-01:**
  the operator may also set a waiver from the **copilot review** — the review step is where they accept or
  override the model's inferences, and forcing them into the technical wizard to waive would push people back
  toward mislabeling. Part C is unchanged: the operator may set one, the LLM may never propose, suggest or
  pre-fill one.
- **P4a — provenance + the capability bond (contracts + registry).** `waived_by` / `waived_at` /
  `waived_capability_id`, **server-stamped at `set_bindings`**, never client-asserted; stage 4 verifies the bond
  (`side_effect_waiver_capability_mismatch`). This closes the gap the P1 follow-up named: the guarantee was
  *registry-emission-side, not a signature*, so a hand-edited manifest could pair a benign justification with a
  dangerous capability and validate clean. Absent provenance stays a warning, never an error (legacy waivers).
- **P4b — audit + fixtures + e2e.** GLEA pack-publish waiver payload (carrying both the justification's author
  and the pack's publisher); ACH fixture migration off mislabeling onto real waivers; the Playwright journey; the
  wizard **ReviewStep** gap (P3 surfaced waived steps in both copilot reviews, but the technical wizard's own
  final review — the last screen before publish — has no gates summary); methodology-guide update (the
  `min_hitl_mode`-as-non-waivable-floor contract is new guidance for MCP implementors).

## Consequences

- **+** The gate becomes a *decision* rather than an obstacle, and the decision is recorded. Today's removal
  path — mislabeling the capability — is untraceable; this one is queryable in the audit store.
- **+** `min_hitl_mode` gains a clear, valuable meaning: the capability author's non-waivable floor. MCP
  implementors get a way to protect their own dangerous tools from downstream process owners.
- **+** The runtime gains its first side-effect enforcement, closing the gap where it blindly trusts the
  manifest.
- **+** The `assist_capability` hole (a genuine, live gap in the invariant we advertise) is closed.
- **−** The platform's strongest trust claim becomes conditional. Every statement of the form "Amendia always
  gates real-world actions" must be restated as "…unless the process owner waived it, with a recorded
  justification." Docs, the trust/accountability business view, and any customer-facing claim need updating.
- **−** SoD coverage shrinks on waived steps: an un-gated step writes no `human` `actor_log` entry
  (`engine/hitl.py:29-53`), so it neither excludes nor can be excluded under `distinct_actor`. A four-eyes
  policy naming a waived element is now meaningless — the validator should warn.
- **−** Additive manifest field ⇒ OpenAPI + `webui/src/api/gen/*` regeneration; several validator/onboarding/UI
  tests assert the current absolutism and will flip.

## Scope boundaries (explicitly not in this ADR)

Multi-MCP-server onboarding (parked, separate). Any change to how `side_effect` is inferred. Any change to the
HITL mode ladder or `hitl_rank`. Runtime behaviour of gated tasks. Multi-instance fan-out of side-effectful
capabilities (Part E keeps it blocked; enabling it needs its own ADR). Retroactive waiver of already-active
packs — waivers ship with a pack version, so existing packs are unaffected.

## Open for confirmation

1. **Part B** — `min_hitl_mode` as the capability author's non-waivable floor. Recommended; gives MCP
   implementors a real lever.
2. **Part C** — the copilot may never set a waiver. Recommended without reservation.
3. **Part E** — side-effectful capabilities stay ineligible as multi-instance hosts. The sharpest consequence of
   allowing `none`; recommended.
4. **Part H** — warn on downgrading an ack-shape-inferred `side_effectful` to `read_only`.
