# ADR-008 — Ingestor service (basic ingestion + ingestion log)

- **Status:** Accepted (initial/basic implementation)
- **Date:** 2026-07-07
- **Related:** ADR-007 (stub exception generator + `exception_raised` event contract);
  `backend/services/ingestor/README.md`; `libs/amendia_common/events.py`
- **Supersedes/advances:** the "Implement ingestion … as a mounted FastAPI sub-app" item in
  `amendia_project_brief.md` (Current Scope).

## Context

Amendia's core flow begins when an exception event lands on the broker: the ingestion service consumes
it, fetches the full exception (and files) from the bank's API, then (later) resolves the exception to a
BPMN process and hands it to the agent runtime. ADR-007 delivered the producer side — the stub publishes
a thin `exception_raised` event and serves a fetch-back API. Nothing consumed those events yet.

We need the **first, deliberately basic** cut of the ingestor: prove the consume → fetch → record loop
end to end, and establish the ingestion-log data model that later stages (process selection, agent-runtime
dispatch) will extend — without building those stages yet.

## Decision

Introduce **`backend/services/ingestor/`**, a FastAPI service that subscribes to `exception_raised`,
fetches the full document from the store, and **logs each ingested exception to MongoDB**. It exposes a
read API over that log. Layout, config, logging, middleware, DI seams, and the Dockerfile mirror the
established service conventions (`stub_exception_generator` / `config-forge-service`).

### What it does today

On each `exception_raised` event:

1. **Validates** the thin event (`IncomingExceptionRaisedEvent`).
2. **Fetches** the full exception document from the store:
   `GET {STUB_BASE_URL}/exceptions/{exception_id}`. The URL is built from a **configured base**, not the
   event's `fetch_url` (which is `localhost`-scoped and would not resolve inside the compose network).
   **Attachments are intentionally ignored** for now — only the JSON document is pulled.
3. **Records** an ingestion-log entry in MongoDB with `status = received`.

### Consumption

- Exchange: `amendia.events` (durable topic, `amendia_common.events.EXCHANGE`).
- Queue: durable `ingestor.exception_raised.v1`, bound with
  `*.stub_exception.exception_raised.v1` — the pattern is built from `amendia_common.events` constants
  (`Service.STUBEXCEPTION`, `EXCEPTION_RAISED`, `Version.V1`), never hand-typed, and matches every tenant.
- The consumer runs as an asyncio task in the FastAPI lifespan (the `notification-service` pattern) with
  jittered reconnect.
- A message that cannot be parsed or handled is **logged and acked** (no poison-requeue). Acceptable for
  the basic cut; a production service would retry / dead-letter.

### Ingestion-log record & lifecycle

One document per exception in the `ingestions` collection, under a **unique index on `exception_id`**, so
a redelivered event for an already-ingested exception is an **idempotent no-op** (logged and skipped).

Each record carries a 3-stage lifecycle. **Only the first is wired today**; the later states,
a `status_history` trail, and repository transition methods (`mark_dispatched/accepted/rejected`) exist so
the agent-runtime work slots in **without a schema change**:

| Status | Meaning | Wired now |
|---|---|---|
| `received` | Event consumed, details fetched, record created | ✅ |
| `dispatched` | Handed over to the agent runtime | ⛔ future |
| `accepted` / `rejected` | The agent runtime's outcome | ⛔ future |

Record shape (abbreviated): `exception_id`, `tenant`, `exception_type`, embedded `event`
(`event_id`, `occurred_at`, `schema_version`, `routing_key`, `fetch_url`), `exception_detail` (the full
fetched envelope, or `null`), `fetch_error` (set if the fetch failed — the event is still logged),
`status`, `status_history[]`, `created_at`, `updated_at`.

### HTTP surface (port 8082)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/ingestions` | List processed exceptions; filters `tenant`/`exception_type`/`status`, `limit`/`offset`, `created_at` desc. |
| `GET` | `/ingestions/{exception_id}` | Full ingestion record. `404` if unknown. |
| `GET` | `/health` | Liveness + readiness (mongo ping + rabbit connection state). |

## Consequences

- The consume → fetch → record loop is proven end to end: generating on the stub produces an event that
  the ingestor consumes, enriches via fetch-back, and persists as `received` (verified against the live
  compose stack).
- The ingestion-log schema is the extension point for the next stages — process-registry lookup and
  agent-runtime dispatch advance the same record through `dispatched` → `accepted`/`rejected`.
- Idempotency is structural (unique `exception_id`), so redelivery and at-least-once broker semantics are
  safe.
- **Known limitations (basic cut):** attachments are not fetched; no process selection and no agent-runtime
  dispatch (those states exist in the model but are never triggered); fetch failures are recorded but not
  retried, and unhandleable messages are acked rather than dead-lettered.
- **Deploy note:** the ingestor's `pyproject.toml` declares the shared lib via a repo-relative path
  (`amendia-common = { path = "../../../libs" }`). `uv` rejects that path in a flattened container image,
  so the ingestor Dockerfile **preserves the repo directory layout under `/src`** — the relative path then
  resolves identically locally and in Docker. This is the pattern to reuse for future nested services.
