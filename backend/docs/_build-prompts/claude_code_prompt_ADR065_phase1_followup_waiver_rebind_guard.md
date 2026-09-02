# Claude Code prompt — ADR-065 P1 follow-up: the waiver must not survive a change to the binding it justifies

Small corrective phase between **ADR-065 P1** (shipped, reviewed) and **P2** (runtime enforcement). P1 is
otherwise accepted: the contract, the nine finding codes, the non-waivable set, the MI rule, the assist fix and
the session round-trip all verified clean against the diff. This prompt closes **one blocking hole** found in
review, plus two small items. Read
`backend/docs/adr/ADR-065-operator-waivable-human-gate-on-side-effectful-capabilities.md` (Part C especially)
and `backend/docs/_build-reports/claude_code_prompt_ADR065_phase1_side_effect_waiver_registry_report.md` first.

## Why

The waiver is preserved across a copilot chat turn keyed on **`element_id` alone**
(`app/services/copilot/reconcile.py:715-722`; `_prior_by_el` is `{b.element_id: b}` at `:208`). But two lines
above the branch, `b.capability_ref = self._cap_ref(tool)` — and `tool` may have **changed in that same turn**,
because `set_executor {element_id, capability_tool}` is in the closed mutation vocabulary
(`app/services/copilot/mutations.py:41-45`, applier at `:241-243`).

So: an operator waives `Task_X` bound to `notify_pega`, writing a justification about an idempotent notification.
A later chat turn rebinds `Task_X` to `execute_payment`. The branch re-attaches the waiver and restores
`hitl_mode = "none"`. Stage 4 then sees a side-effectful capability **with** a waiver → the floor is waived; the
capability *is* side-effectful and the binding *is* below floor, so it is not a dead waiver either. **The pack
validates clean.** A high-risk capability now runs with no human gate, under a justification describing a
different, low-risk one.

ADR-065 Part C says the copilot may never waive a gate. P1 satisfies the letter (no `set_waiver` mutation) but
not the intent: an LLM-proposed `set_executor` can make a human gate disappear from a capability **no human ever
waived**. That must be closed before P2 teaches the runtime to honour waivers — the runtime should not start
trusting a value the registry can produce incorrectly.

## The principle to implement

> A waiver justifies **one capability, gated one way, on one element.** It survives a copilot turn only when
> none of that changed. Any deliberate change to the binding's capability or its gate drops the waiver and
> re-gates the binding, and the operator is told.

Dropping is the fail-safe direction: the binding returns to `approve_actions` via the existing clamp, and the
operator can deliberately re-waive against what the binding now is.

## Deliverable 1 — the rebind/re-gate guard (blocking)

In `reconcile.py` at the preservation branch (`:715-722`):

- **Capability changed ⇒ drop the waiver.** Compare the prior binding's capability against the one resolved this
  turn. Compare the **bare capability id** (the part before `@`), not the full ref with its version range, so a
  routine version-range bump does not spuriously drop a valid waiver. Any change to the id drops it. If the
  comparison is ambiguous for any reason, **drop** — never preserve on a maybe.
- **Gate deliberately raised ⇒ drop the waiver.** The branch currently restores `prior.hitl_mode` /
  `prior.hitl_role` unconditionally, which (my read — **confirm empirically before changing**) means a
  `set_hitl` proposal on a waived binding is silently discarded: an operator asking the copilot to put an
  approval gate back on `Task_X` would have it quietly not happen. If confirmed: when this turn explicitly
  proposes a mode that is **stronger** than the waived one, honour the proposal and drop the waiver — otherwise
  the waiver would be dead anyway and stage 4 would reject the pack with `side_effect_waiver_not_required`.
  **If the premise is wrong — if `set_hitl` already reaches the binding — say so in the report with the evidence
  and implement only the capability-change half.**
- **Tell the operator.** A silently dropped waiver is its own confusion. Emit a `self._det("hitl", eid, ...)`
  decision-trace entry naming what changed (capability rebound, or gate raised), that the waiver was dropped, and
  that the binding was re-gated — so it surfaces in the copilot's decision trace the way every other
  deterministic correction does. Do **not** add a new mutation kind, a new proposal field, or any way for the LLM
  to create or retain a waiver.

**Tests:** waive → `set_executor` to a different side-effectful tool → waiver dropped, binding re-gated to
`approve_actions`, decision-trace entry present, and the resulting pack **fails** stage 4 without a fresh waiver
(prove the hole is closed end to end, not just that a field is `None`). Waive → chat turn touching something
unrelated on that element → waiver **survives** (the existing `test_copilot_chat_preserves_operator_waiver`
must still pass — do not weaken it). Waive → explicit gate raise → waiver dropped, stronger gate applied.

## Deliverable 2 — prove the Part H signal on the real path

`test_read_only_with_ack_shape_output_warns` hand-inserts an ack-shaped schema at `1.1.0` via
`schema_repo.insert`, bypassing the registration gate. That proves the validator branch fires; it does **not**
prove the realistic path produces the signal, and it would keep passing if schema normalization ever started
dropping top-level `properties`.

The deviation is accepted — I verified that `normalize_artifact_schema`
(`app/services/mcp_introspect.py:230-252`) deepcopies and only *adds* `$schema` / `type` / `$id` /
`additionalProperties`, so top-level `properties` survives verbatim and the recomputed signal is faithful. Add
one test that **locks that property in**: a genuinely mislabeled tool (ack-shaped `output_schema`, operator sets
`read_only`) driven through `infer_capability` → `normalize_artifact_schema` → register → validate, asserting
`side_effect_downgraded_from_inference`. Keep the existing test.

## Deliverable 3 — reconcile the test-count baseline

The P1 report states process-registry baseline **405** → 419 (+14). The 2026-08-19 vulnerability-remediation
report records process-registry at **407** after its two upload-413 tests, so the arithmetic should land at 421.
Run `pytest --collect-only -q | tail -1`, establish the true current count, and state in the report whether the
baseline was simply stale **or** two tests were lost in the human-task fixes. If any test was lost, restore it.

## Do not

- Do not touch **agent-runtime** (P2), the **webui** feature code (P3), or GLEA / the ACH fixture (P4).
- Do not add a mutation kind, proposal field, or any other route by which the LLM can create, retain or weaken a
  waiver. The copilot's only legal moves remain: leave an untouched waiver alone, or drop it and re-gate.
- Do not change the contract, the finding codes, their severities, or the non-waivable set — all reviewed and
  accepted.
- Do not weaken `test_copilot_chat_preserves_operator_waiver` to make the new guard pass. Legitimate preservation
  must keep working; if that test now conflicts with the guard, the guard is wrong.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- Waive → rebind to a different capability → **waiver dropped, binding re-gated**, decision-trace entry emitted,
  and a pack built from that session **fails** stage 4 until re-waived.
- Waive → unrelated chat edit → waiver survives; the existing preservation test still green, unmodified.
- Waive → explicit gate raise → stronger gate wins, waiver dropped (or, if the premise is refuted, a documented
  explanation of why no change was needed).
- Part H holds on the real onboarding path, proven by the new test.
- Test-count discrepancy explained in one line, with any lost test restored.
- `pytest` green for process-registry and `libs/amendia_contracts`; agent-runtime untouched (prove it). No
  OpenAPI or generated-type change is expected — say so explicitly if that turns out to be wrong.
- **Reviewer note:** not live until `docker compose build process-registry`.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR065_phase1_followup_waiver_rebind_guard_report.md`
(uncommitted): (1) outcome one-liner; (2) the guard as implemented — exactly what is compared and what triggers a
drop; (3) **the Deliverable 1 gate-raise premise: confirmed or refuted, with the evidence**; (4) the test-count
answer from Deliverable 3; (5) verification — commands and results, including the end-to-end proof that a rebound
waiver now fails validation; (6) anything P2 should know about the waiver's trustworthiness at the registry
boundary. Half a screen is fine — this is a small phase.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Backend-only, and narrower still: `process-registry`
copilot reconcile + tests. Smallest change that makes the waiver trustworthy before P2 threads it into the
runtime. Confirm the gate-raise premise before acting on it; a well-evidenced refutation is a better outcome than
a speculative fix.
