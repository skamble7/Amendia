# Claude Code prompt — ACH cohort test: mock Pega orchestrator + generic trigger ingress

Build the **mock Pega orchestrator** for the ADR-063 cohort worked example, plus the one small platform
addition it needs to inject triggers. This is TEST/dev scaffolding for exercising Cohorts end-to-end with the
ACH exposure segments — not a product feature. The three segment BPMNs
(`backend/docs/methodology/worked-examples/ach_exposure/`) and the `ach-exposure` MCP stub
(`mcp_stub/servers/ach_exposure/`, running at `http://ach-mcp:8075/mcp`) already exist. The grounding is
`backend/docs/design/amendia_ach_cohort_grounding.html`.

## What the mock Pega must do

Stand in for Pega orchestrating one ACH exposure case: fire the **three segment triggers** (one per Amendia
segment) each stamped with the same **`case_id`**, catch each segment's **`notify_pega` handback** and advance
to the next trigger, then emit the final **`process_completed` close message** that disposes the cohort. Every
message carries `case_id` — that's the cohort `correlation_value`.

## How a trigger actually enters Amendia (confirm by reading — this shapes the design)

- `stub_trigger_generator/app/routers/generators.py` — the trigger store: a domain generator produces an
  envelope, `_persist_and_publish` wraps it as a `StoredTrigger` (`app/models/trigger.py`) and publishes a
  `TriggerRaisedEvent` (`app/models/events.py`) on `rk(Service.TRIGGER_SOURCE, TRIGGER_RAISED)` with a
  `fetch_url = {SERVICE_BASE_URL}/triggers/{trigger_id}`.
- `backend/services/ingestor/app/clients/stub_client.py` — **the ingestor always fetches the envelope from its
  configured `STUB_BASE_URL` host**, using only the *path* from the event's `fetch_url`. So an injected
  envelope MUST live in the store the ingestor is configured to hit (the stub-trigger-generator). The Pega
  stub therefore CANNOT self-host fetch-back — it submits envelopes into that store.
- `backend/services/ingestor/app/services/ingestion_service.py` — `_resolve_and_dispatch`: calls the registry
  `/resolve`, which (ADR-063 Phase 2) returns a discriminated `kind` — a normal pack `trigger` OR a
  `cohort_close` when the envelope matches a registered cohort **close schema**. So the close message rides the
  exact same front door; the registry classifies it.
- `mcp_stub/servers/ach_exposure/src/ach_exposure_mcp/handlers.py::notify_pega` — the handback contract:
  `POST ${PEGA_STUB_URL}/amendia/handback` with `{case_id, segment, event, result}`.

## Part 1 — generic envelope-submit endpoint on the trigger store (small, enabling)

The stub-trigger-generator only exposes domain generators (wire, dine_in). Add a **domain-neutral submit
endpoint** so any external producer (our mock Pega) can inject an already-built envelope without a bespoke
generator:

- `POST /triggers` (in `stub_trigger_generator`, e.g. a new `routers/ingress.py` or extend `generators.py`):
  body `{ trigger_type: str, schema_version: str, source?: str, payload: object }`. Generate a `trigger_id`,
  build a `StoredTrigger`, and reuse the existing `_persist_and_publish` (store row + publish
  `TriggerRaisedEvent`). Return the stored trigger + `published`. Keep it domain-blind (no ACH knowledge here —
  the payload is opaque). This is the injection primitive; it also keeps wire/dine coexisting (same store).
- Add a focused test (submit → row persisted → `trigger_raised` published with a correct `fetch_url`).

## Part 2 — the mock Pega orchestrator (`/pega_stub`, repo root)

A small FastAPI web app in a new top-level `pega_stub/` directory. Pure orchestration + a thin UI; no Amendia
internals.

**Endpoints**
- `POST /cases` — start a case. Body `{ case_id?, scenario }` where `scenario ∈ { credit_approve, debit_reject,
  route_uw }` (pick sensible amounts per scenario). Generate a `case_id` if absent. Record case state
  (in-memory dict keyed by `case_id`: scenario, current step, history). Submit **Segment A**'s trigger
  (below) to the trigger store. Return the `case_id` + state.
- `POST /amendia/handback` — what `notify_pega` calls. Body `{ case_id, segment?, event?, result? }`. Look up
  the case; **advance based on the case's tracked step** (robust to a missing/duplicated `segment`): after A →
  submit Segment B's trigger; after B → submit Segment C's trigger; after C → submit the **close** message.
  Idempotent per (case_id, step) — a duplicate handback for an already-advanced step is a no-op. Record each
  handback's `result` in the case history (so the UI can show the recommendation, the instruction, etc.).
- `GET /cases` and `GET /cases/{case_id}` — case state + history (JSON).
- `GET /` — a tiny status UI: a form to start a case (case_id + scenario dropdown + "Run case"), and a live
  list of cases showing each one's progress A → B → C → closed with the captured results. Plain server-rendered
  HTML or a single inline page polling `GET /cases` — keep it minimal, no build step.
- `GET /health`.

**Trigger + close envelopes it submits** (all via `POST {TRIGGER_STORE_URL}/triggers`; every payload carries
`case_id`):

- **Segment A** — `trigger_type: "ach.assess_exposure_requested"`, payload:
  `{ request_type: "AssessExposureRequested", case_id, company, exposure_type, credit_amount, credit_limit,
  debit_amount, debit_limit, overage }` (values per scenario).
- **Segment B** — `trigger_type: "ach.enforce_decision_requested"`, payload:
  `{ request_type: "EnforceDecisionRequested", case_id, rbo_decision, underwriter }` where `rbo_decision`
  (`approve`/`reject`) comes from the scenario (or, nicer: after A's handback the UI can show the recommendation
  and let the operator pick — optional; default to the scenario's preset so the run is hands-free).
- **Segment C** — `trigger_type: "ach.closeout_requested"`, payload:
  `{ request_type: "CloseoutRequested", case_id, instruction }` (`release`/`purge`, derived from B's result).
- **Close** — `trigger_type: "ach.process_completed"`, payload:
  `{ event: "process_completed", case_id, outcome }`. This is what the registry's cohort **close schema** must
  match (see prerequisites) so it classifies as `cohort_close` and disposes the cohort.

**Config (env):** `TRIGGER_STORE_URL` (the stub-trigger-generator in-network base, e.g.
`http://stub-trigger-generator:8081` — confirm the real service name/port on the compose network), `PORT`
(default `9095`), `PEGA_STUB_HOST`.

## Part 3 — compose

`pega_stub/deploy/docker-compose.yml` (mirror `mcp_stub/deploy/docker-compose.yml`): join the backend
`amendia` external network, alias **`pega-stub`**, publish `9095:9095`, set `TRIGGER_STORE_URL` to the trigger
store's in-network URL. (The MCP compose already points `notify_pega` at `http://pega-stub:9095` via
`PEGA_STUB_URL` — keep that alias.) A Dockerfile + pyproject like the MCP stubs.

## Onboarding prerequisites (operator does in the webui; the stub must MATCH these — call them out in the report)

These are set when onboarding the packs / cohort — the stub's envelopes must line up, so document the exact
shapes it emits:
- Each segment pack's **triage rule** keys on its payload `request_type` (A→`ach-exposure-assess`,
  B→`ach-decision-enforce`, C→`ach-closeout`), and each pack's `cohort_membership.correlation_key` is `case_id`.
- The **cohort definition** `ach_exposure_cohort` registers a **close schema** that matches the close envelope
  (`{ event: "process_completed", case_id }`) with `close_correlation_path: case_id` (and
  `close_outcome_path: outcome`). If a small idempotent startup helper in the Pega stub (or a one-shot script)
  can register the cohort definition via the registry API, add it behind a flag — otherwise just document the
  exact close schema to register. Do NOT hardcode registry owner credentials.

## Do not

- Do not modify agent-runtime, the cohort runtime/read code, the ingestor's resolve/close logic, or the MCP
  stub — this is orchestration scaffolding on top of them. The one platform change is the generic submit
  endpoint (Part 1).
- Do not put ACH/domain knowledge in the trigger store's submit endpoint (payload stays opaque).
- Do not have the Pega stub talk to RabbitMQ or fetch-back directly; it submits envelopes to the store over
  HTTP and receives handbacks — nothing else.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- `POST /triggers` on the stub-trigger-generator stores + publishes an arbitrary envelope (test green); wire/
  dine generators still work.
- Starting a case fires Segment A; each `notify_pega` handback advances A → B → C; after C the stub emits the
  `process_completed` close. All four messages carry the same `case_id`. Handbacks are idempotent.
- With the packs + cohort onboarded, a full run opens one cohort, accumulates its three members, and drains to
  `closed` — visible in the cohort views (`GET /cohorts/by-correlation/{case_id}`), with the member BPMN
  diagrams reflecting each segment's execution.
- `pytest` green for `stub_trigger_generator` and the new `pega_stub`; existing suites unaffected.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ach_cohort_pega_stub_and_trigger_ingress_report.md`
(uncommitted): (1) outcome one-liner; (2) the generic submit endpoint; (3) the Pega stub — endpoints,
the A→B→C→close orchestration state machine, the exact envelope shapes it emits, config/compose; (4) the
onboarding shapes the operator must match (triage `request_type`s, `case_id` correlation key, the cohort close
schema); (5) how to run the whole thing end-to-end (backend up → MCP stub → Pega stub → onboard → start a
case); (6) verification + results; (7) anything left open. Keep it to a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. This is test scaffolding: prefer the smallest change
that makes the cohort exercise real. Stay inside `pega_stub/` and the one `stub_trigger_generator` endpoint.
