# ACH Exposure Cohort — onboarding, cohort/SLA setup & run walkthrough

Minimal, reproducible steps to onboard the three segments, register the cohort, **declare the expectation graph
+ an SLA on the new Cohorts screen**, and drive a case (incl. an **SLA-breach** case) from the mock Pega
orchestrator. Fixtures in this folder; concepts in ADR-063 (Cohorts) + ADR-064 (Cohort SLAs); grounding in
`backend/docs/design/amendia_ach_cohort_grounding.html`; SLA authoring guide in
`backend/docs/methodology/cohort_authoring_guide.html`.

> **Sign in as `priya` / `dev-password`.** Onboarding, cohort registration, and the DAG/SLA editor are all
> **`role.process.owner`-gated** — the seeded owner is **priya**. As a non-owner (e.g. `marcus`) you won't see
> the Registry nav or any of the edit controls.

## 0. Prerequisites

- Backend stack up, **rebuilt** for ADR-064 (`docker compose build` then up): `process-registry`,
  `agent-runtime`, `glea-service`, `notification-service`, plus `ingestor`, `stub-trigger-generator`, `webui`.
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
   `schemas/`: A → `art.ach.assess_exposure_requested.json`, B → `art.ach.enforce_decision_requested.json`,
   C → `art.ach.closeout_requested.json`.
3. **Triage rule** — match on `request_type == "<value from table>"`. (`case_id` is always present and is the
   cohort correlation key — see step 4.)
4. **Cohort membership** — set on every pack:
   `cohort_membership: { cohort_def_id: "ach_exposure_cohort", correlation_key: "case_id" }`.
5. **Bind capabilities** to the segment's MCP server (table above). `notify_pega` (the Pega handback) is on all
   three servers; each pack binds its own copy.
6. **HITL** — Segment B's release/purge action tools run under `approve_actions`. Segment B's exclusive gateway
   branches on `decision.rbo_decision` (`approve` → release, `reject` → purge). A and C need no approval gate.

> Segment B enforces **SoD** — the enforce approver must differ from the assessor (e.g. Marcus Bianchi vs Riya
> Sharma). Note this is separate from the *owner* role you use to author cohorts (priya).

## 2. Register the cohort definition (new Cohorts screen)

The Cohorts screen has two tabs: **Instances** (runtime observability, read-only) and **Definitions** (the
design-time config you maintain). Everything in this section is on **Definitions**.

1. **Cohorts → Definitions → `+ New cohort`.** Register the definition once using
   `schemas/cohort.ach_exposure.close.schema.json`:
   - `cohort_def_id`: `ach_exposure_cohort`
   - **close schema**: Pega's end-of-process message `{ event: "process_completed", case_id, outcome }`
   - `close_correlation_path`: `case_id` · `close_outcome_path`: `outcome` (`Released`/`Purged`)
2. **Assign members in the same flow** — add each of the three packs and its correlation key (`case_id`) before
   submitting. (Registering with 0 members then re-submitting 409s; if that happens, delete and re-create with
   members — `DELETE`/membership `PUT` are owner-only.)

The Definitions tab now lists `ach_exposure_cohort` (Members 3). The **Instances** tab stays empty until a case
runs.

## 3. Declare the expectation graph + the closeout SLA (DAG/SLA editor)

This is the ADR-064 step and the point of this run: tell Amendia what to expect and when, so it can flag a
late/missing external invocation. **Do this before running the breach case** — SLAs are **forward-only**: a
cohort instance snapshots the graph *at open*, so the graph must exist before the case starts.

> **Where it lives:** the DAG/SLA editor is **not** on the *New cohort* creation form (that form only captures id / close schema / correlation paths / members). It's on the **definition detail page, in Edit mode** — the **"Expectation graph & SLAs"** card. Register the definition first (§2), then edit it here.

1. **Cohorts → Definitions → `ach_exposure_cohort` → Edit** (owner-only; you're priya).
2. In the **expectation-graph editor**, build the pipeline (all `expected`, all `AND` — no XOR here; the closeout
   is a single segment):
   - **Nodes:** `ach-exposure-assess`, `ach-decision-enforce`, `ach-closeout` (node type **expected**).
   - **Edges:** `__start__ → ach-exposure-assess → ach-decision-enforce → ach-closeout → __close__`.
3. **Add the test SLA — on the `ach-decision-enforce → ach-closeout` edge** ("after enforce hands back, expect
   the closeout to be invoked in time"):
   - **anchor moment:** `completion` (of `ach-decision-enforce`)
   - **satisfy moment:** `arrival` (of `ach-closeout`)
   - **deadline:** `20` seconds · **at-risk:** `12` seconds · **clock:** `wall` · **owner:** `external`
   - (Optional: add an `end_to_end` SLA, or a `START → assess` arrival SLA, for a richer board. Not needed for
     this test.)
4. **Save.** You'll see the **forward-only warning** if instances already exist — edits apply to *future*
   cohorts only. (Save calls the owner-gated `PUT`; an invalid graph surfaces the server's 422 inline.)

The read view now shows the Nodes/Edges tables with the SLA summary (`external · 20s · wall`).

## 4. Invoke a case from the Pega stub

The stub fires A → B → C on each `notify_pega` handback, then emits `process_completed`. Open
`http://localhost:9095`, pick a scenario, **Run case** — or `curl`:

```
curl -X POST http://localhost:9095/cases -H 'content-type: application/json' \
  -d '{"scenario":"late_closeout"}'      # optional: "case_id":"CASE-2026-00SLA1"
```

| Scenario | Company | Decision | Closeout timing | Expected SLA result |
|----------|---------|----------|-----------------|---------------------|
| `credit_approve` | ACME-LOGISTICS | approve | immediate | satisfied (Released) |
| `debit_reject`   | RIVERSIDE-TRUCKING | reject | immediate | satisfied (Purged) |
| `route_uw`       | MIDCITY-RETAIL | approve | immediate | satisfied (Released) |
| **`late_closeout`** | DELTA-FREIGHT | approve | **delayed ~25s** | **BREACHED** then arrived-late (Released) |

`late_closeout` fires A and B normally, then **holds the closeout trigger ~25s** — past the 20s SLA — before
sending it. (Delay is `closeout_delay_seconds` in `src/pega_stub/scenarios.py`, overridable via
`CLOSEOUT_DELAY_SECONDS`.)

## 5. What you should see

**Happy path (`credit_approve` etc.):** cohort opens on Segment A → 3 members join → after Segment C finishes the
close message drains it `open → closing → closed`. The instance SLA panel shows the enforce→closeout SLA
**satisfied**; no breach badges.

**Breach path (`late_closeout`):** watch the **Instances** tab and the cohort **instance detail** — updates
arrive live over SSE (no refresh needed):

1. A and B run and complete as normal.
2. When `ach-decision-enforce` completes, the enforce→closeout SLA clock starts (20s, owner **external**).
3. At **~12s** the SLA goes **at-risk** (amber) — an at-risk badge on the Instances row + an amber chip on the
   instance SLA panel.
4. At **20s** it **breaches** (red) — attributed to **external** (Pega was late invoking closeout). The list row
   shows a breach badge; the SLA panel shows a red `breached` chip with the owner and a "breached Ns ago" time.
5. At **~25s** the closeout trigger finally arrives; the segment runs and completes — the expectation records
   **arrived-late** (the breach **stands** — attribution keeps the truth), and the case closes
   `open → closing → closed`, outcome **Released**.

So the one board shows the whole arc: **on-track → at-risk → breached (external) → arrived-late → closed.** The
breach is surface-only (badge + live SSE update) — there's no email/push in V1 (that's the deferred CB-7).

> Because SLAs are forward-only, run `late_closeout` **only after** the SLA is saved (§3). A case that opened
> before the SLA existed carries no SLA (empty panel) — start a fresh case.

Sample envelopes for each step are in `samples/`.
