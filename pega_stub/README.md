# pega_stub — mock Pega orchestrator (ADR-063 cohort worked example)

Test/dev scaffolding that stands in for Pega orchestrating one **ACH exposure** case across three Amendia
segments. It fires the three segment triggers (A → B → C), each stamped with the same `case_id` (the cohort
`correlation_value`), catches each segment's `notify_pega` handback and advances to the next, then emits the
`process_completed` close message that disposes the cohort.

It never talks to RabbitMQ or fetch-back — it only **POSTs envelopes to the trigger store** (`POST /triggers`
on `stub-trigger-generator`) and **receives handbacks** (`POST /amendia/handback` from the ACH MCP stub).

## Run

```
pip install -e '.[dev]'
TRIGGER_STORE_URL=http://localhost:18081 pega-stub    # standalone (host-published stub store)
# open http://localhost:9095 — pick a scenario, Run case, watch A → B → C → closed
```

In compose it joins the backend `amendia` network as `pega-stub:9095` (see `deploy/docker-compose.yml`). There
`TRIGGER_STORE_INTERNAL_TOKEN` defaults to `dev-internal-token` (matching the backend's
`STUBTRIG_AUTH_INTERNAL_TOKEN`) so the `principal_or_internal`-guarded `POST /triggers` passes out-of-the-box; it
stays overridable via the env var. Dev scaffolding only — not a real secret.

## Endpoints

- `POST /cases` `{case_id?, scenario}` — start a case (scenario ∈ `credit_approve`, `debit_reject`,
  `route_uw`); fires Segment A.
- `POST /amendia/handback` `{case_id, segment?, event?, result?}` — advances A → B → C → close; idempotent per
  `(case_id, segment)`.
- `GET /cases`, `GET /cases/{case_id}`, `GET /health`, `GET /` (status UI).

## Onboarding shapes it matches

See `src/pega_stub/scenarios.py`. Each segment payload leads with a `request_type` the pack triages on
(`AssessExposureRequested` / `EnforceDecisionRequested` / `CloseoutRequested`); every payload carries `case_id`
(each pack's `cohort_membership.correlation_key`). The close payload is `{event: "process_completed", case_id,
outcome}` — register the cohort definition `ach_exposure_cohort` with that close schema,
`close_correlation_path: case_id`, `close_outcome_path: outcome` (or set `REGISTER_COHORT_ON_START=true` +
`REGISTRY_BEARER=<owner token>` to self-register on startup).
