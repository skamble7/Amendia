# ACH Exposure Cohort — onboarding & run walkthrough

Minimal, reproducible steps to onboard the three segments, register the cohort, and drive a case from the
mock Pega orchestrator. Fixtures in this folder; concept in ADR-063; grounding in
`backend/docs/design/amendia_ach_cohort_grounding.html`.

## 0. Prerequisites

- Backend stack up (process-registry, ingestor, agent-runtime, stub-trigger-generator, webui, glea-service).
- The three ACH MCP servers up on the `amendia` network (`mcp_stub/deploy/docker-compose.yml`):
  `ach-assess-mcp:8075`, `ach-enforce-mcp:8076`, `ach-closeout-mcp:8077`.
- The mock Pega orchestrator up (`pega_stub/deploy/docker-compose.yml`): `pega-stub:9095`.

## 1. Onboard the three segment packs

Onboard each BPMN as its **own pack** (webui onboarding wizard). All three share the same shape; only the
trigger schema, triage value, and MCP server differ.

| Segment | Pack key | BPMN | Triage `request_type` | MCP server |
|---------|----------|------|-----------------------|------------|
| A — Assess & Recommend | `ach-exposure-assess` | `ach-exposure-assess.bpmn` | `AssessExposureRequested` | `http://ach-assess-mcp:8075/mcp` |
| B — Enforce & Execute  | `ach-decision-enforce` | `ach-decision-enforce.bpmn` | `EnforceDecisionRequested` | `http://ach-enforce-mcp:8076/mcp` |
| C — Closeout & Purge   | `ach-closeout` | `ach-closeout.bpmn` | `CloseoutRequested` | `http://ach-closeout-mcp:8077/mcp` |

For **each** segment:

1. **Upload the BPMN** from this folder.
2. **Author the trigger (artifact) schema** — the process trigger is a Pega message, not a tool output, so it
   must be authored in the wizard (it cannot be introspected from the MCP server). Use the matching file in
   `schemas/`:
   - A → `art.ach.assess_exposure_requested.json`
   - B → `art.ach.enforce_decision_requested.json`
   - C → `art.ach.closeout_requested.json`
3. **Triage rule** — match on `request_type == "<value from table>"`. This is what routes the inbound trigger
   to this pack. (`case_id` is always present and is the cohort correlation key — see step 4.)
4. **Cohort membership** — set on every pack:
   `cohort_membership: { cohort_def_id: "ach_exposure_cohort", correlation_key: "case_id" }`.
   Each segment maps its own `case_id` trigger field as the correlation key.
5. **Bind capabilities** to the segment's MCP server (table above). `notify_pega` (the Pega handback) is on
   all three servers; each pack binds its own copy.
6. **HITL** — Segment B's release/purge action tools run under `approve_actions` (human approves before the
   side effect). Segment B's exclusive gateway branches on `decision.rbo_decision` (`approve` → release,
   `reject` → purge). A and C need no approval gate.

> Segment B enforces **SoD** — the approver of the enforce action must differ from the assessor. In the
> validated run this was two distinct users (e.g. Marcus Bianchi, Riya Sharma).

## 2. Register the cohort

Create the cohort **definition** once (webui *New Cohort*, or `POST /cohort/definitions` with an owner token —
requires `role.process.owner`). Use `schemas/cohort.ach_exposure.close.schema.json`:

- `cohort_def_id`: `ach_exposure_cohort`
- **close schema**: matches Pega's end-of-process message `{ event: "process_completed", case_id, outcome }`
- `close_correlation_path`: `case_id`  (resolves which cohort instance to close)
- `close_outcome_path`: `outcome`  (`Released` / `Purged`)

**Membership is assigned as part of the same New-Cohort flow** — add each of the three packs and its
correlation key (`case_id`) before submitting. Registering the definition with **0 members** and re-submitting
409s; if that happens, delete the definition and re-create it with the members (membership `PUT/DELETE` and
definition `DELETE` require `role.process.owner`).

At runtime the cohort **instance** is created lazily by the first segment that spawns with a given `case_id`
(first-writer-wins on `correlation_value`); the other two join it. The Cohorts **list** shows instances (via
GLEA), so it stays empty until a case runs — the DEFINITIONS count reflects the registered definition.

## 3. Invoke a case from the Pega stub

The stub POSTs envelopes to the trigger store (`POST /triggers`, guarded by `principal_or_internal`; in compose
its `TRIGGER_STORE_INTERNAL_TOKEN` defaults to `dev-internal-token`). It fires A → B → C on each
`notify_pega` handback, then emits the `process_completed` close message.

Open `http://localhost:9095`, pick a scenario, **Run case** — or:

```
curl -X POST http://localhost:9095/cases \
  -H 'content-type: application/json' \
  -d '{"scenario":"credit_approve"}'      # optional: "case_id":"CASE-2026-001001"
```

Scenarios (`src/pega_stub/scenarios.py`):

| Scenario | Company | Exposure | `rbo_decision` | Expected close outcome |
|----------|---------|----------|----------------|------------------------|
| `credit_approve` | ACME-LOGISTICS | credit +30k | approve | Released |
| `debit_reject`   | RIVERSIDE-TRUCKING | debit +140k | reject | Purged |
| `route_uw`       | MIDCITY-RETAIL | credit +60k | approve | Released |

## 4. What you should see

Cohort **opens** on Segment A → 3 members join → after Segment C finishes, the close message drains it
`open → closing → closed` (exactly one `closed`; `closing` always before `closed`). Cohort detail shows the
close outcome, a `done/running/failed` rollup, and per-member live BPMN diagrams (each greens only its executed
path). External Pega-run steps are noted, not drawn.

Sample envelopes for each step are in `samples/`.
