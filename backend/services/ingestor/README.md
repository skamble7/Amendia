# Ingestor

The **ingestor** is the entry point of Amendia's core flow. It subscribes to `exception_raised`
events on the `amendia.events` RabbitMQ exchange (published by the stub exception generator, ADR-007),
fetches the full exception document from the store, and **logs each ingested exception to MongoDB**.

This is the **basic** first cut: it only subscribes and pulls details. Process selection (via the
process registry) and agent-runtime invocation are future scope — but the data model is already shaped
for them.

## What it does

On each `exception_raised` event:
1. Validates the thin event.
2. Fetches the full exception document from the store: `GET {STUB_BASE_URL}/exceptions/{exception_id}`
   (attachments are ignored for now).
3. Writes an ingestion-log record to Mongo with `status = received`.

Redelivery is idempotent — there is a **unique index on `exception_id`**, so a repeat event for an
already-ingested exception is logged and skipped (one record per exception).

## Lifecycle (status)

Each record carries a 3-stage lifecycle; only the first is wired today:

| Status | Meaning | Wired now |
|---|---|---|
| `received`   | Event consumed, details fetched, record created | ✅ |
| `dispatched` | Handed over to the agent runtime | ⛔ future |
| `accepted` / `rejected` | The agent runtime's outcome | ⛔ future |

The status enum, a `status_history` trail, and repository transition methods
(`mark_dispatched/accepted/rejected`) exist so the agent-runtime work slots in without a schema change.

## Eventing

- Exchange: `amendia.events` (durable topic, `amendia_common.events.EXCHANGE`).
- Queue: durable `ingestor.exception_raised.v1`, bound with `*.stub_exception.exception_raised.v1`
  (built from `amendia_common.events` constants — matches every tenant).
- A message that can't be parsed or handled is logged and **acked** (no poison-requeue).

## Endpoints (port 8082)

| Method | Path | Description |
|---|---|---|
| `GET` | `/ingestions` | List processed exceptions; filters `tenant`/`exception_type`/`status`, `limit`/`offset`, `created_at` desc. |
| `GET` | `/ingestions/{exception_id}` | Full ingestion record. `404` if unknown. |
| `GET` | `/health` | Liveness + readiness (mongo ping + rabbit connection state). |

## Run standalone

Requires reachable MongoDB, RabbitMQ, and the stub. Point the env vars at your own if not using compose.

```bash
cd backend/services/ingestor
uv pip install -e '.[dev]'
cp .env.example .env      # adjust hosts if not using compose
uvicorn app.main:app --port 8082 --reload
```

## Run via docker-compose

From the repo root:

```bash
docker compose -f backend/deploy/docker-compose.yml up --build

# Generate an exception on the stub; the ingestor consumes it automatically.
curl -s -X POST localhost:8081/exceptions/generate -d '{"count":1}'

# See what the ingestor logged
curl -s localhost:8082/ingestions | jq
```

## Tests

```bash
cd backend/services/ingestor
uv pip install -e '.[dev]'
pytest
```

Tests use httpx `AsyncClient` against the app with a faked repository, stub client, and consumer —
no live Mongo/Rabbit/HTTP required.
