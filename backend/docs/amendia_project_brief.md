# Amendia — Payment Exception Handling Platform

## Vision

Amendia is a **generic, agentic payment-exception-handling platform** for banks (personal, commercial, and private banking). Banks define their exception-handling procedures as **BPMN 2.0 processes**; Amendia ingests payment exceptions as events, resolves each exception to the correct process via an **exception registry**, and executes the process through an **AI agent runtime** (LangChain/LangGraph) with **human-in-the-loop approvals** at defined junctures.

The platform is a **product, not a one-off integration**: onboarding a new exception type (e.g., wire payment exceptions — the first target) or a new bank means registering new BPMN process definitions and registry mappings, not writing new code.

## Core Flow

1. An exception event arrives on the message broker; the payload carries an `exception_id`.
2. The ingestion service consumes the event and fetches full exception details and associated files (screenshots, notes, etc.) from the bank's API endpoint.
3. The exception registry maps the exception (by type/attributes) to the bank-defined BPMN 2.0 process that governs its handling.
4. The agent runtime executes the resolved process, pausing at human-approval gates; approvers act via the web UI. (Agent runtime internals are a separate design scope — treat it as a boundary for now.)

## Tech Stack

- **Backend:** Python, FastAPI, MongoDB, RabbitMQ, LangChain/LangGraph
- **Frontend:** React (web UI)
- **Local dev:** docker-compose (backend, MongoDB, RabbitMQ, webui)

## Monorepo Structure

```
amendia/
├── README.md
│
├── backend/
│   ├── deploy/
│   │   └── docker-compose.yml     # Local dev: backend + mongo + rabbitmq (+ webui)
│   │
│   ├── docs/                      # Architecture notes, ADRs, sample BPMN files
│   │
│   ├── libs/                      # Shared Python packages
│   │   ├── domain/                # Core models: Exception, ProcessDefinition, Task, Approval
│   │   ├── bpmn/                  # BPMN 2.0 parsing/validation utilities
│   │   └── clients/               # Bank API clients + internal service-to-service clients
│   │
│   └── services/                  # Each service is an ASGI (FastAPI) app or worker
│       ├── ingestion/             # RabbitMQ event consumer; fetches exception details + files via bank API
│       ├── process-registry/      # Stores BPMN process definitions + exception→process registry (CRUD APIs)
│       ├── agent-runtime/         # Executes resolved processes via LangGraph agents; owns orchestration
│       │                          # and human-in-the-loop task states (design is a separate scope — stub the boundary)
│       └── platform/              # Cross-cutting platform services
│           ├── config-forge/      # Persists application configs (e.g., LLM provider configs)
│           └── notifications/     # SSE/WebSocket push to the front end + inter-service notifications
│
├── stub_exception_generator/      # Dev/test stub: generates synthetic exceptions, saves them to MongoDB,
│                                  # and publishes exception events to RabbitMQ (simulates the bank's systems)
│
└── webui/                         # React app: exception queue, process visualization, approval inbox
```

## Architectural Decisions (already made)

1. **Single-container backend via FastAPI sub-application mounting.** Each service under `backend/services/` exposes its own ASGI app (own middleware, docs, lifespan). A thin top-level `backend/main.py` mounts them (e.g., `app.mount("/registry", registry_app)`) so the whole backend runs as one uvicorn process in one container. Service boundaries stay clean, so splitting into separate containers later is a Dockerfile/compose change, not a refactor.
2. **RabbitMQ is the seam between HTTP-ish and worker-ish components.** The ingestion consumer runs as an asyncio task in the app lifespan (aio-pika). The agent runtime consumes work from RabbitMQ rather than being called in-process over HTTP, keeping it architecturally detached and the first candidate to peel into its own container.
3. **Notifications are broker-backed from day one.** The notification service fans out via RabbitMQ so SSE/WebSocket delivery works regardless of which worker/replica holds a client connection when we scale beyond a single process.
4. **`libs/domain` defines the generic vocabulary** (Exception, ProcessDefinition, HumanTask, Approval). Bank- or payment-type-specific behavior lives in BPMN definitions and registry data — never hardcoded.
5. **MongoDB** stores exceptions, process definitions, registry mappings, configs, and task/approval state.

## Stub Exception Generator (implemented)

`stub_exception_generator/` is a standalone FastAPI service (port **8081**) that **plays the bank's
exception store** for local dev and testing — no auth, no real source connectors, but it implements
the real event contract so downstream services integrate against production-shaped messages. See
**ADR-007** and `stub_exception_generator/README.md` for full detail.

On `POST /exceptions/generate` it: (1) generates a synthetic *unable-to-apply* wire exception
conforming to the normalized envelope `pin.payments.wire_exception/1.0`
(`wire-transfer-exception-reference.md` §4); (2) persists it to MongoDB with store-managed metadata
(`schema_version`, `created_at`, `updated_at`) under a **unique index on `exception_id`** (duplicate
insert → `409`, giving idempotency); and (3) publishes a thin `exception_raised` event. It also serves
the **fetch-back API** — the stand-in for the bank's API endpoint in the Core Flow — returning the full
document and streaming attachment bytes itself.

**Endpoints:** `POST /exceptions/generate`, `GET /exceptions/{id}`, `GET /exceptions` (filterable),
`GET /exceptions/{id}/attachments/{attachment_id}`, `GET /health`.

**Event contract (`exception_raised`).** Published to the single **durable topic** exchange
`amendia.events` (`amendia_common.events.EXCHANGE`). The routing key is built **only** via
`amendia_common.events.rk(tenant, Service.STUBEXCEPTION, EXCEPTION_RAISED)` →
`<tenant>.stub_exception.exception_raised.v1` (canonical `<org>.<service>.<event>.<version>`, e.g.
`bank-alpha.stub_exception.exception_raised.v1`). Message properties: `content_type=application/json`,
persistent delivery, `message_id=event_id`, publisher confirms. The event is **thin** — it announces
the exception and where to fetch it; the full envelope stays out of the bus:

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

Ordering is **persist-then-publish**: insert first, publish only on success; a publish failure is
logged and surfaced via a `warning` field without rolling back the insert (a stub tradeoff — a real
producer would use a transactional outbox).

## Ingestor (implemented — basic)

`backend/services/ingestor/` is a FastAPI service (port **8082**) that is the **entry point of the Core
Flow's consumer side**. It subscribes to `exception_raised`, fetches the full document from the store,
and **logs each ingested exception to MongoDB**. This is the deliberately basic first cut — process
selection and agent-runtime invocation are future scope. See **ADR-008** and
`backend/services/ingestor/README.md`.

On each event it: (1) validates the thin event; (2) fetches the full exception via
`GET {STUB_BASE_URL}/exceptions/{exception_id}` (attachments ignored for now); and (3) writes an
ingestion-log record with `status = received`. It binds a durable queue `ingestor.exception_raised.v1`
to `amendia.events` with `*.stub_exception.exception_raised.v1` (built from `amendia_common.events`
constants). A **unique index on `exception_id`** makes redelivery an idempotent no-op (one record per
exception).

**Lifecycle (3 states; only the first wired today).** The status enum, a `status_history` trail, and
repo transition methods exist so the agent-runtime work slots in without a schema change:

| Status | Meaning | Wired now |
|---|---|---|
| `received` | Event consumed, details fetched, record created | ✅ |
| `dispatched` | Handed over to the agent runtime | ⛔ future |
| `accepted` / `rejected` | The agent runtime's outcome | ⛔ future |

**Endpoints:** `GET /ingestions` (filterable), `GET /ingestions/{exception_id}`, `GET /health`.

## Current Scope

- Scaffold the monorepo per the structure above (Python workspace rooted at `backend/`, pnpm workspace at `webui/`).
- ~~Implement the stub exception generator (synthetic exceptions → MongoDB + RabbitMQ events).~~ **Done** — see the Stub Exception Generator section above and ADR-007.
- Implement ingestion (**done — basic**, see the Ingestor section and ADR-008), process-registry, config-forge, and notifications as mounted FastAPI sub-apps.
- Stub the agent-runtime boundary (queue consumer skeleton only); its internal design is a separate upcoming scope.
- docker-compose for local dev: backend (single container), MongoDB, RabbitMQ, webui.

## Open Questions (do not decide unilaterally — flag for discussion)

- Whether the agent runtime embeds an existing BPMN engine (e.g., Camunda 8/Zeebe, Flowable) with agents as service-task workers, or interprets BPMN 2.0 natively with LangGraph driving execution.
- Exact registry matching semantics (exception type only vs. attribute-based rules).
- ~~Event schema/contract for exception events and the bank API interface shape.~~ **Resolved by ADR-007** for the `exception_raised` event + fetch-back API (as implemented by the stub); the real bank-connector interface may still differ and can map into this same envelope/contract.
