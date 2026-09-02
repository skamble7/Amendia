# ADR-065 P1 follow-up — the waiver must not survive a change to the binding it justifies

**Outcome: DONE and green.** The copilot can no longer let a side-effect waiver outlive the binding it was written
for. A waiver now survives a chat turn only when *neither the capability nor the gate changed*; a deliberate
rebind or an explicit gate-raise drops it, re-gates the binding to the side-effect floor, and records it in the
decision trace. Backend-only, and narrower still: `process-registry` copilot reconcile + tests. Tree left dirty.

## 1. The guard as implemented

`app/services/copilot/reconcile.py` — the waiver-preservation branch in `_binding` (capability executor) now calls
a new `_waiver_drop_reason(prior, new_ref, p)` before preserving. It returns a human-readable reason to **drop**,
or `None` to preserve:

- **Capability changed ⇒ drop.** Compares the **bare capability id** — `ref.split("@", 1)[0]`, via module helper
  `_bare_cap_id` — of the prior binding against the one resolved this turn (`b.capability_ref`, already set from
  the possibly-rebound tool two lines above). Version range is deliberately excluded, so a routine `@^1.0.0 →
  @^1.1.0` bump does **not** drop a valid waiver. **Fail-safe:** either id missing (or unequal) ⇒ drop — never
  preserve on a maybe.
- **Gate deliberately raised ⇒ drop.** Compares the reconstructed+mutated proposal's mode `p.hitl.mode` against
  the waived `prior.hitl_mode` using the **semantic** `hitl_rank` (so `approve_actions ~= manual` — an equivalent
  mode is not "raised"). If `hitl_rank(proposed) > hitl_rank(prior)`, drop and honour the operator's stronger gate.

On drop, the branch falls through to the normal `_clamp_hitl` (which re-gates a side-effectful binding to
`approve_actions`, or keeps the operator's stronger `manual`), sets **no** waiver, and emits
`self._det("hitl", eid, "dropped the operator's side-effect waiver (<reason>) and re-gated …")`. On preserve, the
prior waiver + mode/role are re-attached verbatim, exactly as P1. **No new mutation kind, proposal field, or any
other route for the LLM to create/retain/weaken a waiver was added** — the copilot's only legal moves remain:
leave an untouched waiver alone, or drop it and re-gate.

## 2. The Deliverable-1 gate-raise premise — CONFIRMED

**Premise:** a `set_hitl` proposal on a waived binding was silently discarded — an operator asking the copilot to
put an approval gate back on a waived task would have it quietly not happen.

**Confirmed by source, before patching.** The pre-fix branch assigned `b.hitl_mode, b.hitl_role =
prior.hitl_mode, prior.hitl_role` **unconditionally** whenever a waiver was present, never reading `p.hitl.mode`.
The `set_hitl` mutation edits **only** `p.hitl.mode` / `p.hitl.role` (`mutations.py:234-240`). Therefore on a
waived binding the raise never reached the binding — it was discarded. The fix implements the full half described
in the prompt (honour a strictly-stronger proposal, drop the waiver); `test_copilot_chat_drops_waiver_on_explicit_gate_raise`
now proves a `set_hitl → manual` on a waived binding yields `hitl_mode == "manual"` with the waiver dropped.

## 3. Test-count reconciliation (Deliverable 3)

**True current count: 422 passed, zero failures** (`pytest`, process-registry). **No test was lost — the P1
baseline figure was stale.** Evidence: `git diff -- tests/` shows exactly **one** removed `def test_`, which is
the P1 *rename* `test_send_task_side_effect_guard_unchanged → …_blocked_without_waiver_cleared_with` (its new name
appears in the added set). The three human-task fix files (`test_human_task_inputs`, `test_human_task_outputs`,
`test_refine_artifact`) have **zero** removed test defs — those fixes only added `hitl_mode/hitl_role` to human
`BindingInput`s. The reports' 405/407/421 figures reference different, pre-drift points (all P1 test additions are
uncommitted, and the committed tree moved with the vuln-remediation upload tests + later commits). The internally
consistent arithmetic: P1 working-tree end-state **419 → +3 this phase → 422** (this phase adds exactly the two
copilot tests + one real-path Part-H test below).

## 4. Verification

Commands from `backend/services/process-registry` (`uv run --extra dev pytest`):

| Check | Result |
|---|---|
| full suite | **422 passed** (`pytest -p no:warnings`) |
| the guard, focused | `test_copilot_chat_preserves_operator_waiver` (unchanged, still green), `…_drops_waiver_on_rebind`, `…_drops_waiver_on_explicit_gate_raise` — all pass |
| Part-H real path | `test_read_only_ack_downgrade_survives_real_infer_path` (new) + existing hand-insert test — both pass |
| `libs/amendia_contracts` | **9 passed** (unchanged; the guard imports the existing `hitl_rank`) |
| agent-runtime | **untouched** — `git status --short backend/services/agent-runtime` empty |
| OpenAPI / generated types | **no change this phase** — no contract/API-surface edit; `registry.json`/`registry.ts` remain modified only by P1's additive `side_effect_waiver` field |

**End-to-end proof the hole is closed** (`test_copilot_chat_drops_waiver_on_rebind`): waive `Task_FireTicket`
(side-effectful `fire_ticket`) at `none` → chat `set_executor` rebinds it to a *different* side-effectful tool
(`charge_payment`). Asserted: `capability_ref` is now `cap.rest_stan.charge_payment`; `side_effect_waiver is
None`; `hitl_mode == "approve_actions"` (re-gated); a "dropped the operator's side-effect waiver" decision-trace
entry is present. Then, forcing the binding back to `none` with no waiver and re-assembling makes stage 4 emit
`side_effect_requires_approve_actions` — the stale waiver no longer covers `charge_payment`; a **fresh** waiver
justifying it is required, at which point validation is clean again with a `side_effect_waived` warning. This
proves closure end to end, not merely that a field is `None`.

**Deliverable 2 — Part-H on the real path.** `test_read_only_ack_downgrade_survives_real_infer_path` drives a
genuinely mislabeled tool (ack-shaped `output_schema`, operator sets `side_effect="read_only"`) through
`infer_capability → normalize_artifact_schema → register → validate`, asserting `carries_ack_shape` still holds on
the *normalized* schema and the validator emits `side_effect_downgraded_from_inference`. This locks in the
property the P1 report relied on: `normalize_artifact_schema` deepcopies and only adds keys, so top-level
`properties` survives — if a future normalize ever dropped them, this test (not just the hand-insert one) fails.
The existing hand-insert test is kept.

## 5. For P2 — waiver trustworthiness at the registry boundary

With this guard, a `side_effect_waiver` present on a manifest binding is trustworthy to the extent that **the
registry only ever emits one that a human attached to *this* capability at *this* gate** — the copilot can no
longer forge one onto a rebound or re-gated binding. Two caveats P2's runtime gate should keep in mind when it
starts honouring the waiver off `NodeContext`:

- The guarantee is **registry-emission-side**, not a signature. Nothing cryptographically binds the justification
  text to the capability id; a hand-edited manifest committed out-of-band could still carry a mismatched waiver.
  Stage 4 re-checks *load-bearingness* (dead-waiver / floor) on every validate, but it does not re-verify that the
  justification's prose matches the capability. If P2 wants a stronger bond, that is a new control (e.g. stamping
  the waived capability id + operator into the waiver object), not something P1/this phase provides.
- The waiver drops **fail-safe**: any ambiguity re-gates to `approve_actions`. So the runtime will never see a
  side-effectful node ungated *because* a waiver was silently preserved — worst case it sees a gate that a fresh
  operator waiver could remove.
