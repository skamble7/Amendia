# ACH Exposure Cohort — worked example (segmented cross-system process)

Test fixtures for **ADR-063 (Cohorts)**: a real segmented process where **Pega** orchestrates the whole ACH
exposure-limit-violation case and delegates three agentic segments to **Amendia**. All three segments belong to
one **cohort** (`ach_exposure_cohort`), correlated by the Pega **`case_id`**.

See the full grounding (business explainer + Pega macro flow + segment BPMN sketches):
`backend/docs/design/amendia_ach_cohort_grounding.html`.

## The three Amendia segments (onboard each as its own pack)

| Segment | Pack key | BPMN | Trigger in | Handback |
|--------|----------|------|-----------|----------|
| A — Assess & Recommend | `ach-exposure-assess` | `ach-exposure-assess.bpmn` | `AssessExposureRequested` | `ExposureAssessed` |
| B — Enforce & Execute | `ach-decision-enforce` | `ach-decision-enforce.bpmn` | `EnforceDecisionRequested` | `ExecutionOrchestrated` |
| C — Closeout & Purge | `ach-closeout` | `ach-closeout.bpmn` | `CloseoutRequested` | `CaseClosedOut` |

Each pack, at onboarding, gets:
`cohort_membership: { cohort_def_id: "ach_exposure_cohort", correlation_key: "case_id" }`.

## Conventions

Pure flow, matching the seed packs (e.g. `wire-repair-agentic`): plain `startEvent` / `endEvent`,
`serviceTask` for capability/agent steps, `userTask` for HITL gates, `exclusiveGateway` (FEEL condition) for the
Segment-B approve/reject branch, full BPMNDI for rendering. Executor/capability bindings and HITL modes
(`approve_actions` on Segment B's release/purge gates) are set at onboarding in the annotation manifest, not in
these files.

## Capabilities the segments bind (one MCP server per segment, under `/mcp_stub/servers`)

Each segment onboards against **its own** MCP server (`notify_pega`, the Pega handback, is on all three):

| Segment | MCP server URL | Tools |
|---------|----------------|-------|
| **A — Assess** | `http://ach-assess-mcp:8075/mcp` (`ach_exposure_assess`) | `classify_exposure`, `get_client_risk_profile`, `recommend_disposition`, `draft_underwriting_message`, `notify_pega` |
| **B — Enforce** | `http://ach-enforce-mcp:8076/mcp` (`ach_decision_enforce`) | `capture_decision`, `prepare_release`, `request_purge`, `notify_pega` |
| **C — Closeout** | `http://ach-closeout-mcp:8077/mcp` (`ach_closeout`) | `verify_disposition`, `mark_completed`, `purge_working_data`, `notify_pega` |

The mock Pega orchestrator (its own root directory) fires the three triggers with a shared `case_id`, listens
for each `notify_pega` handback, and emits the final `process-completed` close message that disposes the cohort.
