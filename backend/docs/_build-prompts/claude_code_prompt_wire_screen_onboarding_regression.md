# Claude Code prompt — debug & fix: wire "Screen" re-screen fails and is masked as a compliance hold

You are debugging a **runtime regression** in the Amendia monorepo, then fixing it. This is NOT an ADR-059
task — the vocabulary rename is done and correct. Confirm the root cause empirically **before** changing code;
do not guess-patch.

## Symptom (observed, with evidence)

Wire-repair (`wire-stan`, copilot-onboarded) instances always route to `End_Hold` right after the human
`ApproveRepair`, and the process completes without ever reaching the side-effectful tasks `ApplyRepair` /
`Notify`. In the agent-runtime log the post-approval step is a single `wirefix-mcp` call with **no
`[Screen] … produced` line and no `screening` artifact committed**, then `completed outcome=End_Hold`. The
restaurant pack (`stan-dine`) runs fully green — both `approve_actions` gates (`Task_FireTicket`,
`Task_ProcessPayment`) create a HITL task, wait, and execute the MCP tool only **after** approval. So the HITL
gate engine is healthy; the problem is specific to the wire `Screen` step.

Critical: the **same BPMN + MCP server, onboarded via the copilot, worked before the recent ~217-file
changeset**. It now holds. So a regression landed in that changeset on the copilot onboarding and/or the
capability-invocation path.

## Root-cause hypothesis (confirm, don't assume)

`Bnd_Hit` on `Screen` is a **catch-all error boundary** (`<bpmn:errorEventDefinition/>`, no `errorRef`) in
`backend/docs/methodology/worked-examples/wire_transfer/wire-repair-agentic.tobe.bpmn`. The engine routes to it
only when the MCP result is `isError` (ADR-035 → `CapabilityBusinessError`, see
`agent-runtime/app/engine/executor/mcp_client.py::_raise_if_business_error`). The stub
`screen_party` (`mcp_stub/servers/wire_transfer_exception/src/wire_transfer_exception_mcp/handlers.py`)
**never sets `isError`** for a normal `clear`/`hit` result and, for creditor "Aurora Chemicals SpA" + `hint`
"done", returns `status: "clear"`. So a hold means the `screen_party` **call itself errored** and the catch-all
boundary disguised that technical failure as a "compliance hold."

The most likely trigger: `screen_party` reads `party = _payload(args, "party", "envelope")`, and `_payload`
checks **top-level keys only** (no nested fallback — unlike `_dig` used for `hint`). If the copilot-onboarded
pack now sends Screen's arguments **nested** under the input-artifact name (`{"screen_party_input": {"party":
…}}`) instead of flat top-level fields, `_payload` returns a non-dict and `party.get("creditor")` throws → the
tool returns `isError` → boundary → hold. Verify this is what actually happens.

## Read first

- `backend/docs/methodology/worked-examples/wire_transfer/wire-repair-agentic.tobe.bpmn` — `Screen`, `Bnd_Hit`,
  flows `f_app_screen` / `f_screen_apply` / `bf_Bnd_Hit`.
- `mcp_stub/servers/wire_transfer_exception/src/wire_transfer_exception_mcp/handlers.py` — `screen_party`,
  `_payload`, `_dig`, `_name`; and `schemas.py` — `SCREEN_INPUT` / `SCREEN_OUTPUT` / `SCREENING_STATUSES`.
- `agent-runtime/app/engine/task_runner.py` — the capability path and the MCP-argument builder
  (`_mcp_arguments(...)`, used when `ctx.input_map` is set); how a `fields`-composite `input_map` becomes the
  tool arguments.
- `agent-runtime/app/engine/executor/mcp_client.py` (`_raise_if_business_error`, `call_tool`) and
  `executor/dispatch.py` — how an MCP `isError` / `{"business_error"}` becomes `CapabilityBusinessError`, and
  how a technical `CapabilityError` differs.
- The copilot onboarding path in `process-registry/app/services/copilot/**` and
  `process-registry/app/services/onboarding.py` — specifically where a binding's `input_map` (the `fields`
  composite for `screen_party_input`) and the MCP argument shape are derived from tool introspection.
- Reference for comparison: `agent-runtime/seed/wire-repair-agentic/capabilities/cap.payment.sanctions_screen.json`.

## Tasks

1. **Reproduce and capture the truth first.** Bring the stack up, onboard `wire-stan` via the copilot as the
   user does (or reuse the active pack), fire an `unable_to_apply` trigger, drive it to `ApproveRepair`, approve.
   Capture, at DEBUG, the **exact `screen_party` MCP request arguments and the response** (is `isError` set?
   what shape are the args?). Also call the stub `screen_party` directly (flat args vs nested-under-
   `screen_party_input`) to prove which shape errors. State the confirmed mechanism before touching code.

2. **Bisect the regression.** With read-only git (`git log`, `git diff` — no commits), diff the copilot
   onboarding + MCP-argument-building + tool-introspection paths between the last-good commit (immediately
   before the ADR-059 changeset landed) and HEAD. Identify the change that altered the Screen argument shape (or
   the input-map derivation). Name the file/line.

3. **Fix the root cause** so the `screen_party` call receives the argument shape the tool expects and returns
   `clear`, letting the flow proceed `Screen → ApplyRepair` (its `approve_actions` gate) `→ Notify` (its gate)
   `→ Record → End_Resolved`. Fix it at the correct layer (the argument builder / copilot input-map derivation),
   not by loosening the stub — unless the bisect shows the stub itself regressed.

4. **Secondary robustness (smaller, keep separate in the diff).** A **catch-all error boundary turning a
   technical capability failure into a silent `End_Hold` is a real masking bug.** Make the engine distinguish a
   genuine modeled business error (a real screening hit with a declared `error_code`) from a technical
   `CapabilityError`/fallback `_MCP_TOOL_ERROR` with no real code: the latter should surface as instance
   **failed** (or a distinct, logged outcome), not a compliance hold. At minimum, log loudly when a
   fallback-coded `CapabilityBusinessError` is routed to a catch-all (no-`errorRef`) boundary.

5. **Sanity-check adjacent copilot wirings** exposed by the same onboarding: `Screen.hint` ←
   `approved_repair.justification` (freeform text as a screening hint) and `Notify.recipients` ←
   `related_messages` (a camt array, not recipients). Determine whether these are additional copilot
   mis-derivations; fix if wrong, or note why they're acceptable.

## Do not

- Do not change the ADR-059 vocabulary, routing keys, queues, `trigger_messages`, or fetch-back paths.
- Do not weaken HITL gating or the `approve_actions` path (it is correct — dine-in proves it).
- Do not run git write ops (add/commit/push/branch). Leave the tree dirty; the operator owns commits.
- Do not edit reference-domain data to paper over the bug unless the bisect proves the stub/data regressed.

## Acceptance

- The confirmed root cause is stated with the captured MCP request/response and the bisected commit/file.
- A wire `unable_to_apply` trigger now runs the **happy path** end to end: `Screen` clears, `ApplyRepair` and
  `Notify` each raise an `approve_actions` gate that waits for a human and executes the MCP tool **only after**
  approval, and the instance ends `End_Resolved` (not `End_Hold`).
- `stan-dine` still runs fully green (no regression).
- A genuinely-failing `screen_party` call no longer completes as a silent `End_Hold` — it surfaces as a failure
  (or a clearly-logged, distinct outcome).
- Backend `pytest` green for `agent-runtime` and `process-registry`.

## Final step — implementation report (required)

Write a concise report to `backend/docs/_build-reports/claude_code_prompt_wire_screen_onboarding_regression_report.md`
(create `_build-reports/` if absent; do **not** commit). Cover: (1) outcome one-liner; (2) the confirmed root
cause with the captured `screen_party` request/response and the bisected commit+file; (3) the fix, by file, and
which layer; (4) the secondary robustness change; (5) verdict on the `hint`/`recipients` wirings; (6) exact
verification — commands run and results (repro, e2e wire happy path, dine-in regression check, `pytest`);
(7) anything left open or needing the reviewer. Keep it to a screen or two — it's the cover sheet Claude reviews.

## Working agreement

You do not run git write commands — leave the tree dirty for Sandeep to review and commit. Prefer a real fix at
the right layer over a shim. Stay inside the Amendia repo and the scope above.
