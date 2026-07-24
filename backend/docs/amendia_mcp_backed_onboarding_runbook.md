# Amendia — MCP-backed process onboarding runbook (the real target, not the seed)

**Goal:** onboard the thorough wire-transfer exception process (full swimlanes/roles, ADR-34→46 BPMN surface)
**backed by a real MCP server** — every activity executes a tool on `wirefix-mcp:8060`, not the seed's in-code
`skill`/`llm` capabilities. This is the production pattern: a process + its MCP capabilities onboarded as **data**,
with the platform assuming nothing.

Everything here is **operator data/config in the wizard** — no platform code change. The one prerequisite from
the platform side is **P0** of the domain-neutrality batch (remove the `default_domain="payment"` fallback +
collision guardrail); until P0 lands you achieve the same result manually by **setting a distinct domain at the
Basics step** (below). Do **not** reuse the seed `cap.payment.*` capabilities — those are the v1 in-code
implementations.

## Prerequisites

- The wire-transfer MCP server running and reachable at the deployment-facing endpoint `http://wirefix-mcp:8060/mcp`
  (`mcp_stub/deploy/docker-compose.yml`), exposing the 10 tools, each compliant with the MCP Implementor Guideline
  (declared `inputSchema`/`outputSchema`, closed shapes, required decision fields, acknowledgement shape on
  actions, `isError`+`error_code` for modeled business errors).
- The corrected to-be BPMN (`wire-repair-agentic.tobe.bpmn` in `backend/docs/bpmn/`): 4 lanes (AI Agent, Ops
  Analyst, Ops Approver, Supervisor), the repair/return/RFI branches, the SLA timer boundary (`PT4H`) on
  ApproveRepair → Escalate, and the screening error boundary on Screen → compliance hold. Parses with 0 errors.
- The `stub_exception_generator` running, to raise a test exception for execution.

## Element → MCP tool map (this process)

| BPMN element | Kind | MCP tool (on wirefix) | Capability id (domain `wirefix`) | side_effect |
|---|---|---|---|---|
| Enrich | serviceTask | `enrich_investigation` | `cap.wirefix.enrich_investigation` | read_only |
| Assess | serviceTask | `assess_beneficiary` | `cap.wirefix.assess_beneficiary` | read_only |
| DraftRepair | serviceTask | `draft_repair` | `cap.wirefix.draft_repair` | read_only |
| Screen | serviceTask | `screen_party` | `cap.wirefix.screen_party` | read_only |
| ApplyRepair | serviceTask | `apply_repair` | `cap.wirefix.apply_repair` | **side_effectful** |
| Notify | serviceTask | `notify_parties` | `cap.wirefix.notify_parties` | **side_effectful** |
| Record | serviceTask | `record_resolution` | `cap.wirefix.record_resolution` | read_only |
| DraftReturn | serviceTask | `draft_return` | `cap.wirefix.draft_return` | read_only |
| ExecuteReturn | serviceTask | `execute_return` | `cap.wirefix.execute_return` | **side_effectful** |
| ObtainInfo / ApproveRepair / ApproveReturn / Escalate | userTask | — (human) | — | — |

`draft_rfi` is exposed by the server but this diagram routes RFI through the human **ObtainInfo** task, so it need
not be onboarded (tool whitelisting — onboard only the tools the process binds).

## Steps

**1 · Basics.** New pack (e.g. `pack_key = wire-exception-agentic`, `version = 1.0.0`). **Set the default domain
to a process-scoped namespace that is NOT `payment` — use `wirefix`.** This makes every derived capability id
`cap.wirefix.<tool>`, so nothing collides with the seeded `cap.payment.*`. (Post-P0 the wizard requires you to
pick a domain and flags a collision if you don't.)

**2 · BPMN.** Attach `wire-repair-agentic.tobe.bpmn`. Confirm coverage: 13 bindable elements, 4 lanes, the SLA
timer boundary registers on ApproveRepair, the screening error boundary on Screen.

**3 · Capabilities.**
- **3a · Introspect** `http://wirefix-mcp:8060/mcp`. Select the 9 tools this process uses; each becomes a
  `cap.wirefix.<tool>` of `kind: mcp` whose `runtime.tools` whitelists exactly that tool, with its input/output
  artifacts inferred from the tool schemas.
- **3b · Mark the action tools side-effectful.** Per Implementor Guideline §4, Amendia can't infer this from MCP —
  **you** set it. Flip `apply_repair`, `notify_parties`, `execute_return` to `side_effectful`. This engages the
  `approve_actions` HITL floor for those bindings.
- **3c · Assess is an MCP tool (decided).** `Assess` is a **serviceTask** in the to-be BPMN (regenerated
  2026-07-21; parses with 0 errors), so it binds `cap.wirefix.assess_beneficiary` like any other capability task —
  no DMN, no decision authoring. That tool's `repair_verdict` output (`repairable|unrepairable|needs_info`) is the
  field the gateway routes on. (Native DMN stays available for a future process that specifically wants a
  business-owned decision table; this pack is fully MCP-backed.)

**4 · Bindings.** Each capability task now pre-fills its `cap.wirefix.<tool>` (ids match — no collision). Set HITL:
`apply_repair`/`execute_return`/`notify_parties` → `approve_actions` (+ an approver role); `draft_repair`/
`draft_return` → `review_after` if you want a check; human tasks already carry lane-inferred roles/HITL.

**4a · Author the input data-flow (`input_map`) — REQUIRED for execution (ADR-048).** Per-tool MCP artifacts do
**not** chain on their own: the entry task's input isn't seeded from the trigger, and `enrich_investigation_output`
≠ `assess_beneficiary_input`, so nothing feeds the next step. Without wiring, the pack activates but fails at the
first node (`missing required input 'enrich_investigation_input' … have: []`). For each capability task, declare
where its input comes from: the entry task (`Enrich`) sources `from: trigger` (the exception envelope); each later
task sources `from: artifact` = the upstream task's output (e.g. `Assess.dossier ← enrich_investigation_output`,
`DraftRepair ← assess_beneficiary_output`, …). This is the ADR-048 `input_map`; the wizard pre-suggests it
(entry→trigger, schema-match→upstream output) and you confirm.

**5 · Triage.** Add at least one rule whose `when` matches the sample exception envelope your generator emits
(the earlier "no match" info was just a mismatched sample — align the rule or the sample so the smoke test hits).

**6 · Policies.** Separation-of-duties: approver ≠ agent on ApproveRepair/ApproveReturn (the wizard suggests SoD
candidates from the lanes); confirm pack roles.

**7 · Gateway variables.** Map `Gw_Repairable` → variable `repair_verdict`, source artifact =
`cap.wirefix.assess_beneficiary`'s output artifact (`art.wirefix.assess_beneficiary_output`), which carries the
required `repair_verdict` field. Ensure the branch conditions and the mapped variable share a namespace — your
flows read `beneficiary.repair_verdict`, so either map the variable under `beneficiary` or adjust the conditions
to the mapped name. This clears the Stage-6 `gateway_without_variable` warning.

**8 · Review & activate.** The dry-run should be clean of the IO-mismatch cluster (ids resolve to your MCP caps)
and the HITL-floor errors (you set the side-effect gates). One warning is **not** benign: the per-tool
`unproduced_input` items. Pre-ADR-048 they surface as soft warnings but predict a hard runtime failure at the entry
task — do **not** treat them as cosmetic. Post-ADR-048 they become real data-flow validation: an input you didn't
map and nothing produces is an **error**, and once you author the `input_map` (step 4a) the flow validates cleanly.
The only genuinely benign warning is the `LaneSet` documented-element note. Activate once the data-flow is either
authored (ADR-048) or the pack is knowingly a structure-only dry run.

> **Known prerequisite for execution:** the runbook's execute step assumes ADR-048 (`input_map`) is in place. Until
> it lands, an introspected per-tool-artifact pack activates but fails at the first node — the data-flow is
> unwired. Author the `input_map` (step 4a) on a platform with ADR-048, or the run will fail at `Enrich`.

**9 · Execute.** With the `input_map` authored (step 4a), raise a test exception via `stub_exception_generator`
(drive a specific branch with the reason code / repair hint the stub honours). Watch the instance: `Enrich`
sources its input from the trigger and calls its tool on `wirefix-mcp:8060`; each later task sources from the
upstream output and calls its tool; the side-effectful actions pause at their `approve_actions` gate for four-eyes;
`Gw_Repairable` routes on `repair_verdict`; the SLA timer escalates an un-approved repair after `PT4H`; a
`SCREENING_HIT` `isError` from `screen_party` routes to the compliance-hold error boundary. That is the full
ADR-34→46 surface executing against a real MCP server — the thing we set out to build.

## Why this is the real target (not the seed)

The seed `cap.payment.*` capabilities are v1 **in-code** `skill`/`llm` implementations (`app.capabilities.
wire_repair.*`) — useful as a reference, but they are exactly the process-in-the-platform coupling ADR-047
removes. This runbook onboards the **same process as data**: BPMN + registered artifacts + `mcp` capability
descriptors pointing at an external server. Nothing here assumes the seed; swap in any other process + its MCP
server and the same nine steps apply.
