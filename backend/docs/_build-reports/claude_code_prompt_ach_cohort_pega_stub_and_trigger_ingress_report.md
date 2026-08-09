# ACH cohort test — mock Pega orchestrator + generic trigger ingress: report

## 1. Outcome

Test/dev scaffolding to exercise ADR-063 Cohorts end-to-end with the ACH exposure segments: a **generic
envelope-submit endpoint** on the trigger store (the one small platform addition) + a new **mock Pega
orchestrator** (`pega_stub/`) that fires the three segment triggers (A → B → C) — each stamped with the same
`case_id` — advances on each `notify_pega` handback, then emits the `process_completed` close. Both suites
green; no agent-runtime / cohort / ingestor / MCP changes.

## 2. The generic submit endpoint (Part 1)

`POST /triggers` on `stub_trigger_generator` (added to the store surface, `app/routers/triggers.py`): body
`{ trigger_type, schema_version, source?="external", payload }`. Generates a `trigger_id`, builds a
`StoredTrigger`, and reuses the existing `_persist_and_publish` (store row + publish `TriggerRaisedEvent` on
`trigger_source.trigger_raised.v1` with `fetch_url = {SERVICE_BASE_URL}/triggers/{id}`). **Domain-blind** — the
payload is opaque here (no ACH/wire/dine knowledge); wire/dine generators are untouched and coexist in the same
store. Test `tests/test_submit_ingress.py` (submit → persisted + fetch-back + `trigger_raised` published with a
correct `fetch_url`; opaque payload; 422 guards).

## 3. The mock Pega orchestrator (Part 2, `pega_stub/`)

A small FastAPI app (`src/pega_stub/`), pure orchestration — it only POSTs envelopes to the trigger store and
receives handbacks (never RabbitMQ, never fetch-back).

**Endpoints:** `POST /cases {case_id?, scenario}` (fires Segment A), `POST /amendia/handback
{case_id, segment?, event?, result?}` (advances), `GET /cases`, `GET /cases/{id}`, `GET /scenarios`,
`GET /health`, `GET /` (a build-free live status UI: start a case + a table polling `/cases` showing A → B → C →
closed with captured decision/outcome).

**State machine (`orchestrator.py`):** per-case in-memory state tracks `completed` segments + `step`. A handback
advances by the case's **own tracked step**, robust to a missing/aliased `segment` (canonicalises `A|B|C` from
common aliases, else falls back to the next-expected segment — the pipeline is strictly in order). **Idempotent
per (case_id, segment):** a duplicate/late handback for an already-completed segment is a no-op; a closed case
ignores further handbacks. On A → decide `rbo_decision` (honour A's `recommendation` when decisive; ROUTE_UW/
absent → the scenario preset) → fire B; on B → derive `instruction` (approve→release / reject→purge) → fire C;
on C → derive `outcome` (Released/Purged) → emit close.

**Envelope shapes it emits** (`scenarios.py`; every payload carries `case_id`):
- **A** `trigger_type: ach.assess_exposure_requested` → `{request_type: "AssessExposureRequested", case_id,
  company, exposure_type, credit_amount, credit_limit, debit_amount, debit_limit, overage}`.
- **B** `ach.enforce_decision_requested` → `{request_type: "EnforceDecisionRequested", case_id, rbo_decision,
  underwriter}`.
- **C** `ach.closeout_requested` → `{request_type: "CloseoutRequested", case_id, instruction}`.
- **close** `ach.process_completed` → `{event: "process_completed", case_id, outcome}`.

Scenarios: `credit_approve` (→ approve → release → Released), `debit_reject` (→ reject → purge → Purged),
`route_uw` (A recommends ROUTE_UW; hands-free preset approve → Released). Amounts are per-scenario presets.

**Config/compose (Part 3):** `TRIGGER_STORE_URL` (default `http://stub-trigger-generator:8081`), `PORT` (9095),
`PEGA_STUB_HOST`, optional `TRIGGER_STORE_INTERNAL_TOKEN` (sent as `X-Amendia-Internal`). `Dockerfile` +
`pyproject` mirror the MCP stubs; `deploy/docker-compose.yml` joins the backend `amendia` external network,
alias **`pega-stub`**, publishes `9095:9095` (the ACH MCP compose already points `notify_pega` at
`http://pega-stub:9095`). Optional flagged cohort self-registration (`REGISTER_COHORT_ON_START` +
`REGISTRY_BEARER`, off by default — **no owner creds hardcoded**).

## 4. Onboarding shapes the operator must match

- **Triage** (per segment pack) keys on the payload `request_type`: A → `AssessExposureRequested`
  (rule `ach-exposure-assess`), B → `EnforceDecisionRequested` (`ach-decision-enforce`), C →
  `CloseoutRequested` (`ach-closeout`).
- **Membership**: each segment pack's `cohort_membership.correlation_key = "case_id"` (top-level in every
  payload).
- **Cohort definition** `ach_exposure_cohort` close schema (matches the close envelope):
  ```json
  { "type": "object", "required": ["event", "case_id"],
    "properties": { "event": {"const": "process_completed"}, "case_id": {"type": "string"}, "outcome": {"type": "string"} } }
  ```
  with `close_correlation_path: "case_id"`, `close_outcome_path: "outcome"`. (Exactly
  `pega_stub/src/pega_stub/scenarios.py::COHORT_CLOSE_SCHEMA`.)

## 5. Run it end-to-end

1. Backend up: `docker compose -f backend/deploy/docker-compose.yml up -d --build`.
2. MCP stubs: `docker compose -f mcp_stub/deploy/docker-compose.yml up -d --build` (`ach-mcp:8075`).
3. Pega stub: `docker compose -f pega_stub/deploy/docker-compose.yml up --build` (`pega-stub:9095`).
4. In the webui: onboard the three ACH segment packs (triage `request_type`s above; membership
   `correlation_key=case_id`) and register the `ach_exposure_cohort` definition with the close schema above.
5. Open `http://localhost:9095`, pick a scenario, **Run case** — Segment A dispatches; each segment's
   `notify_pega` hands back to the Pega stub, which fires B, then C, then the close.
6. Watch it in the cohort views: `GET /cohorts/by-correlation/{case_id}` (or the Cohorts UI) shows one cohort
   opening, accumulating three members, and draining to `closed`, with each member's BPMN reflecting its run.

## 6. Verification

- `stub_trigger_generator`: `uv run --extra dev pytest` → **42 passed** (+3 ingress; wire/dine unaffected).
- `pega_stub`: `uv run --extra test pytest` → **11 passed** (start→A, full A→B→C→close with one shared
  `case_id`, reject→purge, route_uw preset, per-segment idempotency, missing-segment advance, unknown-case,
  closed-case no-op, endpoints, health/index).

## 7. Left open

- **Cohort definition registration** is manual in the webui by default (owner-gated); the flagged self-register
  helper needs a `REGISTRY_BEARER` (documented, off by default). The exact close schema to paste is in §4.
- The `notify_pega` handback's `result` shape is pack-binding-dependent; the orchestrator reads
  `result.recommendation` when present and otherwise uses the scenario preset, so a run is hands-free regardless
  of what the segment passes back.
- No live end-to-end run performed here (needs the compose stack + onboarded packs) — the report documents the
  exact steps + shapes; the orchestration + ingress are unit/endpoint-verified.
