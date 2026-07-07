# ADR-007 — Stub Exception Generator & the `exception_raised` event contract

- **Status:** Accepted
- **Date:** 2026-07-07
- **Related:** ADR-006 (normalized wire exception envelope, triage mapping, generator randomization);
  `backend/docs/wire-transfer-exception-reference.md`; `libs/amendia_common/events.py`
- **Resolves:** the "Event schema/contract for exception events and the bank API interface shape"
  open question in `amendia_project_brief.md`.

## Context

Amendia's core flow starts when an exception event arrives on the broker carrying an
`exception_id`; the ingestion service then fetches the full exception (and its files) from **the
bank's API**. In development we have no real bank source. We need something that behaves like a
bank's exception store so the ingestor, process-registry, and agent-runtime can be built and tested
end to end.

We also need to pin down, concretely, **what an exception event looks like on the wire** — the
exchange, the routing key, the message properties, and the payload — because every downstream
service depends on that contract.

## Decision

Introduce **`stub_exception_generator/`**, a standalone FastAPI service that *plays the bank's
exception store*. It is a dev/test component (no auth, no real source-system connectors) but it
implements the real event contract so downstream services integrate against production-shaped
messages.

### What it does

On request it:

1. **Generates** a synthetic wire-transfer exception (the *unable-to-apply* scenario) conforming to
   the normalized envelope `pin.payments.wire_exception/1.0` (reference doc §4). It randomizes what
   the caller does not pin — reason code (`AC01|AC04|RC01|BE04`), settlement amount (10k–5M), UETR,
   `exception_id` (`EXC-<year>-<6-digit>`), party names, and attachment presence — so triage rules
   and all BPMN branches get exercised.
2. **Persists** the exception to MongoDB, wrapped with store-managed metadata: `schema_version`
   (always `pin.payments.wire_exception/1.0`), `created_at`, `updated_at`. A **unique index on
   `exception_id`** makes re-inserts fail as HTTP `409` — cheap idempotency.
3. **Publishes** a thin `exception_raised` event to RabbitMQ (contract below).
4. **Serves the fetch-back API** — it is the store, so it returns the full document and streams
   attachment bytes itself. This is the stand-in for "the bank's API endpoint" in the core flow.

### HTTP surface (port 8081)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/exceptions/generate` | Generate `count` (≤20) exceptions; persist, publish, return stored docs + routing key per event. `201`. |
| `GET`  | `/exceptions/{exception_id}` | Full stored document (the `fetch_url` target). `404` if unknown. |
| `GET`  | `/exceptions` | List with `tenant`/`exception_type`/`status`/`reason_code` filters, `created_at` desc, `limit`/`offset`. |
| `GET`  | `/exceptions/{exception_id}/attachments/{attachment_id}` | Stream canned attachment bytes with the correct `Content-Type`. `404` if missing. |
| `GET`  | `/health` | Liveness + readiness (mongo ping + rabbit connection state). |

### Event contract — `exception_raised`

The event is **thin by design**: it announces that an exception exists and where to fetch it. The
full envelope is **not** put on the bus — consumers call `fetch_url` for details. This keeps messages
small, avoids schema-coupling every consumer to the full payload, and mirrors how a real bank drops a
lightweight notification and exposes details behind an API.

- **Exchange:** `amendia.events` — a single **durable topic** exchange for all Amendia services
  (`amendia_common.events.EXCHANGE`).
- **Routing key:** built **only** via `amendia_common.events.rk(...)`, never hand-assembled. The
  tenant is the `org` segment and the service is `Service.STUBEXCEPTION`:

  ```
  rk(tenant, Service.STUBEXCEPTION, EXCEPTION_RAISED)
    → "<tenant>.stub_exception.exception_raised.v1"
    e.g. "bank-alpha.stub_exception.exception_raised.v1"
  ```

  Format is the canonical `<org>.<service>.<event>.<version>`, so consumers can bind with topic
  patterns like `*.stub_exception.exception_raised.v1` or `bank-alpha.stub_exception.#`.
- **Message properties:** `content_type = "application/json"`, **persistent** delivery mode,
  `message_id = event_id`, and **publisher confirms** enabled (publish awaits broker ack).

**Payload:**

```json
{
  "event_id": "375cfda7-bb51-4993-be8e-1e9da3e23bc8",
  "occurred_at": "2026-07-07T15:53:23.969815Z",
  "schema_version": "pin.payments.wire_exception/1.0",
  "exception_id": "EXC-2026-000123",
  "tenant": "bank-alpha",
  "exception_type": "unable_to_apply",
  "fetch_url": "http://localhost:8081/exceptions/EXC-2026-000123"
}
```

| Field | Type | Meaning |
|---|---|---|
| `event_id` | uuid4 string | Unique per event; also the AMQP `message_id` (dedupe key for consumers). |
| `occurred_at` | UTC ISO-8601 | When the event was emitted. |
| `schema_version` | string | Envelope schema the referenced document conforms to. |
| `exception_id` | string | The stored exception's id; stable fetch key. |
| `tenant` | string | Owning bank/tenant; also the routing-key `org` segment. |
| `exception_type` | string | `unable_to_apply` for this scenario; lets consumers pre-filter. |
| `fetch_url` | URL | Absolute URL to `GET` the full stored document from the store. |

### Ordering & failure semantics: persist-then-publish

The service **inserts into Mongo first and publishes only after a successful insert**. If the publish
fails, it **logs loudly, keeps the insert**, and returns the exception with a `warning` field rather
than rolling back. This is an acknowledged non-transactional tradeoff acceptable for a stub; a real
producer would use a transactional outbox. Documented so callers don't mistake a `warning` response
for a lost exception.

## Consequences

- Downstream services (ingestor first) can develop against a real, production-shaped event + fetch-back
  API without any bank connector. The ingestor binds a durable queue to `amendia.events` with
  `*.stub_exception.exception_raised.v1` and calls `fetch_url`.
- The `exception_raised` event schema and routing convention are now the **canonical contract**; the
  brief's corresponding open question is resolved.
- `libs/amendia_common` gains a backward-compatible `EXCEPTION_RAISED = "exception_raised"` constant so
  producers and consumers share the event name instead of typing strings.
- The stub is **not** an ingestion path and ships no consumers — that is the ingestion service's scope.
- Because publish is not transactional, a `warning`-flagged exception exists in the store but was not
  announced; re-generating or a future replay/outbox mechanism would be needed to surface it. Out of
  scope for the stub.
