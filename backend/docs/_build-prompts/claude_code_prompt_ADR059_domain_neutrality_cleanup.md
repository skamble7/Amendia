# Claude Code prompt — ADR-059: domain-neutrality cleanup (exception → trigger, single trigger-message store)

You are implementing **ADR-059** in the Amendia monorepo. Read
`backend/docs/adr/ADR-059-domain-neutrality-cleanup-trigger-vocabulary-and-store-consolidation.md`
in full before writing any code — it is the contract; this prompt is the execution plan. Also skim
ADR-047 and ADR-049 (the domain-neutrality lineage this completes).

## Goal in one line

Finish the `exception → trigger` rename across **platform code, wire contracts, the dev trigger source, and
the webui platform surface**, and consolidate the stub's two domain collections (`exceptions`, `tickets`)
into **one `trigger_messages` collection** — while leaving reference-**domain data** (wire + dine payloads,
seed packs, domain MCP servers, schema-version ids) domain-named.

## Canonical rename (apply everywhere in scope — this is the source of truth)

| Was | Becomes |
|---|---|
| `EXCEPTION_RAISED = "exception_raised"` | `TRIGGER_RAISED = "trigger_raised"` |
| `EXCEPTION_DISPATCHED = "exception_dispatched"` | `TRIGGER_DISPATCHED = "trigger_dispatched"` |
| `Service.STUBEXCEPTION = "stub_exception"` | `Service.TRIGGER_SOURCE = "trigger_source"` |
| `ExceptionDispatchedEvent` | `TriggerDispatchedEvent` |
| field `exception_id` (all platform models/events) | `trigger_id` |
| field `exception_type` | `trigger_type` |
| field `exception_schema_version` | `trigger_schema_version` |
| literal `pin.platform.exception_dispatched/1.0` | `pin.platform.trigger_dispatched/1.0` |
| `StoredException` / `StoredTicket` | `StoredTrigger` (single wrapper) |
| `ExceptionRepository` / `TicketRepository` | `TriggerRepository` (single) |
| collections `exceptions` + `tickets` | `trigger_messages` (single) |
| `IncomingExceptionRaisedEvent` | `IncomingTriggerRaisedEvent` |
| `ExceptionStoreClient` (agent-runtime) / `StubClient` (ingestor) | `TriggerStoreClient` |
| `exception_id_ctx` (logging_conf, 3 services) | `trigger_id_ctx` |
| service dir `stub_exception_generator/` | `stub_trigger_generator/` |
| routing key `stub_exception.exception_raised.v1` | `trigger_source.trigger_raised.v1` |
| routing key `ingestor.exception_dispatched.v1` | `ingestor.trigger_dispatched.v1` |

`DISPATCH_ACCEPTED` / `DISPATCH_REJECTED`, their `pin.platform.dispatch_*` literals, the ingestion status
enum (`received/dispatched/accepted/rejected/no_process`), and the `ingestions` collection are already
neutral — keep them, but rename their `exception_id` field → `trigger_id`.

## DO NOT rename (reference-domain data — out of scope; touching these is a bug)

- Seed packs `wire-repair-standard`, `wire-repair-agentic`; `backend/docs/methodology/worked-examples/**`.
- Domain MCP servers `mcp_stub/servers/wire_transfer_exception`, `mcp_stub/servers/restaurant_dinein`.
- Inside the stub: the domain contract modules (`app/contracts/wire_exception.py`, the dine/`party_seated`
  module), `app/sample_data.py`, `app/generator.py` (wire) and `app/dining_generator.py` (dine), the
  `WireExceptionEnvelope` / `PartySeatedEnvelope` classes and their `SCHEMA_VERSION` constants, the wire
  `ReasonCode` set and dine demo flags.
- Domain schema-version ids: `pin.payments.wire_exception/1.0` and the dining one.
- Any field **inside** a domain payload: `order_type`, `reason_codes`, `beneficiary`, `party_size`, etc.
- Historical ADRs — do not rewrite them. This ADR is the forward record.

The webui "TYPE" column keeps showing the domain discriminator **value** (`unable_to_apply`, `dine_in`) —
that is data, not a label to rename.

## Read these before editing (grounding — do not assume)

- `libs/amendia_common/amendia_common/events.py` — `Service`, `Version`, event constants, `rk()`, `EXCHANGE`.
- `libs/amendia_contracts/amendia_contracts/dispatch.py` — `ExceptionDispatchedEvent`, `DispatchAcceptedEvent`,
  `DispatchRejectedEvent`, `DispatchResolution`, `Trace`, `DispatchRejectionReason`. (Do **not** touch
  `process_pack.py::TriggerSource` — already neutral.)
- Stub `backend/services/stub_exception_generator/app/`: `config.py`, `db/mongo.py`, `deps.py`, `main.py`,
  `dal/exceptions_repo.py`, `dal/tickets_repo.py`, `models/envelope.py`, `models/ticket.py`,
  `models/events.py`, `models/api.py`, `models/dining_api.py`, `routers/exceptions.py`, `routers/tickets.py`,
  `routers/generators.py`, `events/rabbit.py`, `logging_conf.py`, `pyproject.toml`, `Dockerfile`.
- Ingestor `backend/services/ingestor/app/`: `config.py`, `models/events.py`, `models/ingestion.py`,
  `services/ingestion_service.py`, `clients/stub_client.py`, `clients/registry_client.py`,
  `dal/ingestion_repo.py`, `events/rabbit.py`, `events/publisher.py`, `events/reply_consumer.py`,
  `logging_conf.py`, `main.py`.
- Agent-runtime `backend/services/agent-runtime/app/`: `services/dispatch_service.py`,
  `clients/registry_client.py`, `logging_conf.py`, `config.py`, `models/process_instance.py`.
- Notification `backend/services/platform/notification-service/app/events/`: `signal_mapper.py`, `consumer.py`.
- Webui `webui/src/`: `app/AppShell.tsx`, `router.tsx`, `features/exceptions/**`, `features/inbox/InboxPage.tsx`,
  `api/services/stub.ts`, `api/signalToKeys.ts` (+ `.test.ts`), `api/gen/{stub,ingestor,runtime}.ts`,
  `api/types.ts`, `features/dashboard/**`. Find the OpenAPI codegen script in `webui/package.json`.
- `backend/deploy/docker-compose.yml` (or wherever compose lives) and `tools/demo_wire_repair.sh`.

Use `rg -n 'exception' backend libs webui --glob '!**/docs/**'` to build the full hit-list and reconcile it
against the DO-NOT-rename set above before you start. Wire the change so every hit is either renamed or
consciously left as domain data.

---

## Phase 1 — Backend (land together; the shared symbols couple these services)

Renaming a shared constant/field breaks every importer at once, so the whole backend is one green-able unit.
Implement in this order, then run the full backend suite green before committing the phase.

**1a. Shared libs.** `amendia_common/events.py`: rename the two event constants and the `Service` member/value
per the table. `amendia_contracts/dispatch.py`: rename `ExceptionDispatchedEvent → TriggerDispatchedEvent`,
its fields (`exception_id/type/schema_version → trigger_*`), the `schema_version` literal, and the
`exception_id` field on `DispatchAcceptedEvent` / `DispatchRejectedEvent`; update `Trace` docstrings
("exception journey" → "trigger journey", default "set to trigger_id"). `_event_name` for the dispatched
event becomes `TRIGGER_DISPATCHED`.

**1b. Stub → `stub_trigger_generator`.**
- Rename the service directory `stub_exception_generator → stub_trigger_generator`; update `pyproject.toml`
  name/packaging, `Dockerfile`, and any imports.
- Config: env prefix `STUBEXC_ → STUBTRIG_`; single `MONGO_COLLECTION` default `trigger_messages`; **remove**
  the tickets-collection setting.
- **One store.** Introduce `StoredTrigger` = `{ trigger_id, trigger_type, schema_version, source,
  payload: dict, created_at, updated_at }` and a single `TriggerRepository` over `trigger_messages` with a
  unique index on `trigger_id` (duplicate → `DuplicateTriggerError` → HTTP 409). Delete
  `exceptions_repo.py` / `tickets_repo.py` and the `StoredException` / `StoredTicket` models. `db/mongo.py`
  owns the one collection + index.
- **Neutral event.** Replace `models/events.py::ExceptionRaisedEvent` with `TriggerRaisedEvent`
  `{ event_id, occurred_at, schema_version, trigger_id, trigger_type, fetch_url }`. Keep a `from_envelope`-style
  constructor per domain if convenient, but the wire path must set `trigger_type` from its discriminator
  (today `exception_type`) and the dine path from `order_type`, exactly as today.
- **Routers (neutralize the surface).** Collapse `routers/exceptions.py` + `routers/tickets.py` into a store
  surface plus catalog-driven generation:
  - `GET /triggers/{trigger_id}` → the **clean domain `payload`** (both domains; strip store metadata, per
    ADR-047 D1 — this is the behaviour the dine path already had; the wire path changes to match).
  - `GET /triggers` → list with `trigger_type` / `status` filters (replaces `GET /exceptions`).
  - `GET /triggers/{trigger_id}/attachments/{attachment_id}` → attachment bytes (unchanged logic).
  - `POST /generators/{generator_id}/generate` (`generator_id ∈ {wire, dine_in}`) → calls the domain
    generator (`generate_envelope` / `generate_ticket`), wraps into `StoredTrigger`, publishes one
    `TriggerRaisedEvent` on `rk(Service.TRIGGER_SOURCE, TRIGGER_RAISED)`. Replaces `/exceptions/generate`
    and `/tickets/generate`.
  - Update `routers/generators.py::build_catalog` so each generator's `endpoint` points at the new
    `/generators/{id}/generate` path; keep the scenario derivation (reason codes / dine flags) intact.
  - `fetch_url` in the published event must be `{base}/triggers/{trigger_id}` for both domains.
- Keep `generator.py`, `dining_generator.py`, `sample_data.py`, `contracts/*`, `models/api.py`,
  `models/dining_api.py` domain-named; only their *storage/publish wiring* changes.

**1c. Ingestor.** `models/events.py::IncomingExceptionRaisedEvent → IncomingTriggerRaisedEvent`
(`trigger_id/type`). `models/ingestion.py`: `IngestionRecord.{exception_id→trigger_id,
exception_type→trigger_type, exception_detail→trigger_detail}`; `EventRef` unchanged except any exception
wording; keep the status enum + `ingestions` collection. `clients/stub_client.py`: rename
`StubClient → TriggerStoreClient`, method `fetch_exception → fetch_trigger` (fallback path becomes
`/triggers/{trigger_id}`). `services/ingestion_service.py`: rename all `exception_*` locals/params, use
`trigger_id_ctx`, publish `TriggerDispatchedEvent`, update log strings. `events/rabbit.py`: `BINDING_KEY`
→ `trigger_source.trigger_raised.v1` (built from the renamed constants). `config.py`:
`RABBITMQ_QUEUE = "ingestor.trigger_raised.v1"`; keep `RABBITMQ_REPLY_QUEUE`. `dal/ingestion_repo.py`:
rename the `exception_id` key field/methods → `trigger_id`. `logging_conf.py`: `exception_id_ctx →
trigger_id_ctx`.

**1d. Agent-runtime.** `services/dispatch_service.py`: consume `TriggerDispatchedEvent`; rename
`event.exception_id → trigger_id` throughout; `compute_idempotency_key(trigger_id, …)` (rename its param in
`models/process_instance.py`); `Trace.correlation_id` defaults to `trigger_id`; reply events carry
`trigger_id`. `clients/registry_client.py`: `ExceptionStoreClient → TriggerStoreClient`. `logging_conf.py`:
`exception_id_ctx → trigger_id_ctx`. `config.py`: dispatch queue default →
`agent-runtime.trigger_dispatched.v1` (env `AGENTRT_RABBITMQ_DISPATCH_QUEUE`). The `_validate_trigger`
helper is already domain-neutral — leave its logic, fix only wording.

**1e. Notification-service.** `events/consumer.py`: import `TRIGGER_RAISED/DISPATCHED`; `BINDING_KEYS` →
`ingestor.trigger_dispatched.v1` and `trigger_source.trigger_raised.v1`. `events/signal_mapper.py`: map the
new event names in `event_type()` / `to_signal()`; if a signal `type` string is derived from the event name
it becomes `trigger_raised` / `trigger_dispatched` — note the exact strings you emit, Phase 2 must match them.

**Phase 1 acceptance:** `rg -n 'exception' backend libs --glob '!**/docs/**'` returns only allowed
domain-data hits (wire/dine contracts, sample data, seed packs, `wire_exception` schema id) — reconcile the
list explicitly. All backend unit/integration suites green (`pytest` per service, including the stub, ingestor,
agent-runtime, notification tests). No queue, routing-key, collection, or schema-literal still says
"exception" in platform code.

## Phase 2 — Webui

- `app/AppShell.tsx`: nav item → `{ to: "/triggers", label: "Triggers", … }`. `router.tsx`: route path +
  lazy import → the renamed feature.
- Rename `features/exceptions/ → features/triggers/`: `ExceptionsPage→TriggersPage`,
  `ExceptionDetailPage→TriggerDetailPage`, `ExceptionSummary→TriggerSummary`,
  `GenerateExceptionButton→GenerateTriggerButton` (button copy is already "Generate trigger"), `queries.ts`
  query keys/paths, and `exceptions.test.tsx→triggers.test.tsx`. Update the import in
  `features/inbox/InboxPage.tsx`.
- `api/services/stub.ts`: point generation at `POST /generators/{id}/generate` (keep the catalog-driven
  `listGenerators` / `generateTrigger` shape); update fetch/list paths to `/triggers`.
- `api/signalToKeys.ts` (+ test): map `trigger_dispatched` (the exact string Phase 1e emits) and change the
  react-query key from `["exception", id]` → `["trigger", id]`; update `signalToKeys.test.ts` fixtures.
- **Regenerate** `api/gen/{stub,ingestor,runtime}.ts` from the updated backend OpenAPI via the existing
  codegen script (find it in `package.json`; it needs the services' `/openapi.json`). Do not hand-edit the
  generated files if the script runs; if it cannot run in this environment, update them by hand to exactly
  match the new schema (`StoredTrigger`, `trigger_id/type`, new paths) and say so.
- `features/dashboard/**` and `api/types.ts`: rename platform-label uses of "exception"; leave discriminator
  values alone.

**Phase 2 acceptance:** `npm run typecheck` (or `tsc --noEmit`) and `npm test` green; `rg -n 'xception'
webui/src` returns nothing (or only domain-value fixtures). The UI shows a "Triggers" nav item and the
generate control still lists both generators from the catalog.

## Phase 3 — Deploy + end-to-end + cleanup

- `docker-compose.yml`: service `stub-exception-generator → stub-trigger-generator` (build context/Dockerfile
  path, container name, `depends_on` refs from ingestor and webui); env prefix `STUBEXC_ → STUBTRIG_` with
  `…_MONGO_COLLECTION: trigger_messages` and the tickets-collection var removed; ingestor
  `INGESTOR_STUB_BASE_URL: http://stub-trigger-generator:8081` and `INGESTOR_RABBITMQ_QUEUE:
  ingestor.trigger_raised.v1`; agent-runtime `AGENTRT_RABBITMQ_DISPATCH_QUEUE:
  agent-runtime.trigger_dispatched.v1`. Update any reverse-proxy/webui `VITE_STUB_BASE` route if it names the
  old service.
- **Clean-slate migration (ADR-059 D4):** no back-compat. `docker compose … down -v` before bringing the
  stack up so old volumes/queues/collections are gone. After the demo run, verify Mongo has
  `trigger_messages` and **no** `exceptions` / `tickets` / `sample_exceptions` collections (drop any stray
  ones you find and trace what created them).
- Run `tools/demo_wire_repair.sh` (and, if present, the dine-in demo) against the fresh stack — the full
  `generate trigger → ingest → resolve → dispatch → instance → HITL` path must complete green for **both**
  reference packs on the new vocabulary. Watch the notification stream reaches the webui.

**Phase 3 acceptance:** stack boots clean from `down -v`; both reference demos pass end to end; RabbitMQ
shows the new queue/binding names bound to `trigger_source.trigger_raised.v1` and `ingestor.trigger_dispatched.v1`;
Mongo shows only `trigger_messages` for trigger storage.

---

## Working agreement (per the Amendia bridge model)

- **You do not run git.** Do not `git add`, `commit`, `push`, branch, or amend. Leave the tree dirty; the
  operator (Sandeep) reviews the diff and owns all commits. If you think a checkpoint is warranted, say so in
  your summary — don't do it.
- Do not edit files outside the Amendia repo, and do not touch the DO-NOT-rename set.
- Prefer real fixes over shims; if a rename forces a hard design choice not covered by the ADR, stop and
  surface it rather than guessing.
- When done, report per phase: what changed, the `rg 'exception'` residual reconciliation, test results
  (backend `pytest`, webui `typecheck`/`test`), the e2e demo outcome, and anything you deliberately left as
  domain data.
```
