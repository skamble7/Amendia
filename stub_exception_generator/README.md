# Stub Exception Generator

A dev/test stub that **mimics a bank's exception store** for the Amendia platform.
It does not connect to any real source. On demand it:

1. Generates a synthetic **wire-transfer exception** (unable-to-apply scenario),
2. Persists it to MongoDB (the store), and
3. Publishes a thin **exception-raised event** to RabbitMQ.

It is also the **fetch-back API**: downstream services receive the thin event, then
call this service to fetch the full exception document and its attachment bytes.

The stored document conforms to the normalized wire exception envelope
(`pin.payments.wire_exception/1.0`, see `backend/docs/wire-transfer-exception-reference.md` §4),
wrapped with store-managed metadata (`schema_version`, `created_at`, `updated_at`).

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/exceptions/generate` | Generate `count` exceptions (all body fields optional); persist, publish, return the stored docs + routing key per event. `201`. |
| `GET`  | `/exceptions/{exception_id}` | Fetch the full stored document. `404` if unknown. |
| `GET`  | `/exceptions` | List with optional `tenant`/`exception_type`/`status`/`reason_code` filters, `created_at` desc, `limit`/`offset`. |
| `GET`  | `/exceptions/{exception_id}/attachments/{attachment_id}` | Stream the canned attachment bytes with the correct `Content-Type`. `404` if missing. |
| `GET`  | `/health` | Liveness + readiness (mongo ping + rabbit connection state). |

### `POST /exceptions/generate` body (all optional)

```json
{
  "tenant": "bank-alpha",
  "reason_code": "AC01",          // one of AC01 | AC04 | RC01 | BE04
  "amount": 250000.00,
  "currency": "USD",
  "include_attachments": true,     // true=both, false=none, omit=varied
  "count": 1                        // default 1, max 20
}
```

Anything not pinned is randomized per exception: reason code, settlement amount
(10k–5M), fresh UETR, fresh `exception_id` (`EXC-<year>-<6-digit>`), party names, and
attachment presence. `reason_narrative` is kept coherent with the reason code.

## Eventing

- Durable topic exchange `amendia.events` (`amendia_common.events.EXCHANGE`).
- Routing key is built via `amendia_common.events.rk(tenant, Service.STUBEXCEPTION, EXCEPTION_RAISED)`
  → e.g. `bank-alpha.stub_exception.exception_raised.v1`.
- Published with persistent delivery, `content_type=application/json`, `message_id=event_id`,
  and publisher confirms enabled.

The published event is **thin** (not the full envelope):

```json
{
  "event_id": "<uuid4>",
  "occurred_at": "<UTC ISO-8601>",
  "schema_version": "pin.payments.wire_exception/1.0",
  "exception_id": "EXC-2026-000123",
  "tenant": "bank-alpha",
  "exception_type": "unable_to_apply",
  "fetch_url": "http://localhost:8081/exceptions/EXC-2026-000123"
}
```

### Persist-then-publish tradeoff

The insert happens first; the event is published only after a successful insert. If
publish fails, the stub **logs loudly and keeps the insert**, returning the exception
with a `warning` field (it does not roll back). This is intentional for a stub — a real
producer would use an outbox/transactional pattern.

## Run standalone

Requires a reachable MongoDB and RabbitMQ (or point the env vars at your own).

```bash
cd stub_exception_generator
uv pip install -e '.[dev]'          # installs the service + ../libs (amendia_common)
cp .env.example .env                # adjust hosts if not using compose
uvicorn app.main:app --port 8081 --reload
```

## Run via docker-compose

From the repo root:

```bash
docker compose -f backend/deploy/docker-compose.yml up --build
```

Then:

```bash
# Generate one exception
curl -s -X POST localhost:8081/exceptions/generate \
  -H 'content-type: application/json' -d '{"count":1}' | jq

# Fetch it back (use the exception_id from the response)
curl -s localhost:8081/exceptions/EXC-2026-XXXXXX | jq

# Fetch an attachment
curl -s localhost:8081/exceptions/EXC-2026-XXXXXX/attachments/att-1 --output screen.png
```

The RabbitMQ management UI (`http://localhost:15672`, guest/guest) shows the message on
the `amendia.events` exchange — bind a temp queue with `bank-alpha.stub_exception.#`.

## Tests

```bash
cd stub_exception_generator
uv pip install -e '.[dev]'
pytest
```

Tests use httpx `AsyncClient` against the app with a faked repository and publisher —
no live Mongo/Rabbit required.
