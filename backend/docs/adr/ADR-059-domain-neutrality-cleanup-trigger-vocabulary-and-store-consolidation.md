# ADR-059 — Domain-neutrality cleanup: "trigger" vocabulary and a single trigger-message store

**Status:** Proposed — 2026-08-07
**Date:** 2026-08-07
**Context owner:** Sandeep Kamble
**Relates:** ADR-047 (platform domain-neutrality — runtime decoupling), ADR-049 (domain-neutral trigger
schema as a first-class per-pack input; eviction of domain payload contracts from `amendia_contracts`),
ADR-007/008/009/011 (the stub → ingestor → dispatch → runtime pipeline), ADR-058 (GLEA events).
Supersedes the residual "exception" vocabulary those earlier ADRs left in place.

## Context

Amendia began as a payment **exception**-handling product and was refactored (ADR-047, ADR-049) into a
generic, domain-neutral process-execution platform. The runtime, the pack manifest, the triage predicate
tree, and the onboarding copilot are now domain-neutral: a pack declares its own **trigger** schema
(`ProcessPackManifest.trigger`, ADR-047 D1) and **triage rules** over that trigger's fields, and the engine
validates the fetched payload against that schema without importing any concrete envelope type. The
restaurant dine-in pack proves this — it onboards end-to-end with zero wire coupling.

But the *inbound-payload* vocabulary was never finished. The word **"exception"** — a payments-domain term —
is still baked into **platform code and wire contracts**, not just into the reference wire domain's data:

1. **The wire vocabulary is the platform's default.** `amendia_common.events` defines `EXCEPTION_RAISED` /
   `EXCEPTION_DISPATCHED` and `Service.STUBEXCEPTION`; `amendia_contracts.dispatch` defines
   `ExceptionDispatchedEvent` with `exception_id` / `exception_type` / `exception_schema_version` and the
   pinned platform schema literal `pin.platform.exception_dispatched/1.0`. Every consumer (ingestor,
   agent-runtime, notification-service) binds queues on `*.exception_raised.*` / `*.exception_dispatched.*`
   and threads `exception_id` through its models, logging context, and idempotency keys — none of which is
   domain data; it is platform plumbing named after one domain.

2. **The dev trigger source is mis-named and stores per-domain.** `stub_exception_generator` already emits
   **two** domains — wire "unable-to-apply" exceptions (`EXC-*`) and restaurant dine-in tickets (`TKT-*`) —
   but it is named for one of them, and it persists each domain in its **own domain-named collection**
   (`exceptions`, `tickets`), behind two repositories (`ExceptionRepository`, `TicketRepository`) and two
   stored models (`StoredException`, `StoredTicket`). Two collections for what is, to the platform, one
   concept (an inbound trigger to fetch and triage) is the same domain leak, one layer down. (A stray
   `sample_exceptions` collection is also present.)

3. **The webui surface says "Exceptions."** The primary operator nav item, route (`/exceptions`), and the
   entire `features/exceptions/` folder (`ExceptionsPage`, `ExceptionDetailPage`, `ExceptionSummary`,
   `GenerateExceptionButton`) are named for the wire domain, even though the generate control is already a
   domain-neutral, catalog-driven "Generate trigger" button and the list shows both `unable_to_apply` and
   `dine_in` rows.

The already-neutral parts confirm the target vocabulary is **"trigger"**: ADR-049 ("domain-neutral trigger
schema"), `ProcessPackManifest.trigger`, `TriggerSource` (`from: "trigger"`), the copilot's
`resolve_trigger_schema` / `DeclareTriggerRequest`, the stub's `/generators` "trigger generators" catalog,
and the webui's `generateTrigger()`. This ADR finishes that migration through the inbound-payload plane
before a more complex feature is built on top of a half-neutral base.

### Why "trigger" (and not another word)

"Trigger" is already the platform's established neutral term for *the inbound thing that initiates a run*
(ADR-049). It is precise (it is what fires triage → dispatch → a process instance), domain-free, and needs
no new vocabulary. Alternatives were rejected: "event" and "signal" and "message" already carry specific
**BPMN** meanings inside Amendia (message/signal start & intermediate events, ADR-031 message correlation),
so reusing them for the inbound payload would overload them; "case" collides with the process *instance*.
The one accepted overload is minor: the stored inbound payload is called a **trigger message**, which sits
alongside BPMN "messages" — but those are distinct concepts (mid-process correlation vs. the initiating
payload) and the collection name `trigger_messages` keeps the noun unambiguous.

## Decision

Complete the exception → **trigger** rename across **platform code, wire contracts, the dev trigger source,
and the webui platform surface**, and consolidate the stub's two domain collections into **one
`trigger_messages` collection**. Domain-specific **data** (the wire and dine reference domains) keeps its
domain names — neutrality is required of the *platform*, not of a domain's own payloads.

### D1 — Canonical vocabulary

| Concept | Was | Becomes |
|---|---|---|
| Inbound payload (concept) | exception | **trigger** |
| Stored inbound payload | StoredException / StoredTicket | **StoredTrigger** ("trigger message") |
| Natural key field | `exception_id` / `ticket_id` | **`trigger_id`** |
| Discriminator field | `exception_type` | **`trigger_type`** |
| Trigger store collection | `exceptions` + `tickets` | **`trigger_messages`** (single) |
| Producer service (role) | `Service.STUBEXCEPTION = "stub_exception"` | **`Service.TRIGGER_SOURCE = "trigger_source"`** |
| Event: raised | `EXCEPTION_RAISED = "exception_raised"` | **`TRIGGER_RAISED = "trigger_raised"`** |
| Event: dispatched | `EXCEPTION_DISPATCHED = "exception_dispatched"` | **`TRIGGER_DISPATCHED = "trigger_dispatched"`** |
| Dispatch event model | `ExceptionDispatchedEvent` | **`TriggerDispatchedEvent`** |
| Pinned schema literal | `pin.platform.exception_dispatched/1.0` | **`pin.platform.trigger_dispatched/1.0`** |
| Dev service | `stub_exception_generator` | **`stub_trigger_generator`** |

Routing keys become `trigger_source.trigger_raised.v1` and `ingestor.trigger_dispatched.v1`. The
already-neutral `DISPATCH_ACCEPTED` / `DISPATCH_REJECTED` events and their `pin.platform.dispatch_*` schema
literals are unchanged **except** their `exception_id` field → `trigger_id`. The ingestion status enum
(`received / dispatched / accepted / rejected / no_process`) and the `ingestions` collection are already
neutral and are unchanged.

### D2 — One trigger-message store (the stub)

- A single generic wrapper model **`StoredTrigger`** — `{ trigger_id, trigger_type, schema_version, source,
  payload: dict, created_at, updated_at }` — and one **`TriggerRepository`** over one collection
  **`trigger_messages`**, with a unique index on `trigger_id` (duplicate insert → 409, preserving today's
  idempotency). The store is domain-blind: it never reads a domain field; the whole domain envelope lives
  under `payload`.
- The domain **generators stay domain-specific data**: `generate_envelope` (wire) and `generate_ticket`
  (dine) still produce their own domain envelopes; the router wraps each into a `StoredTrigger`
  (`trigger_id` = the domain id, `trigger_type` = the domain discriminator, `payload` = the envelope) and
  emits one generic `TriggerRaisedEvent`. The domain contract modules (`wire_exception.py`,
  `party_seated.py`), `sample_data.py`, and reason-code / dine-flag scenarios keep their domain names.
- **Fetch-back is unified and neutral: `GET /triggers/{trigger_id}`** returns the **clean domain `payload`**
  (per ADR-047 D1: `additionalProperties:false` trigger schemas must not see store metadata). This
  standardises the two domains — the wire path previously returned the stored row *with* metadata; it now
  returns the clean payload like the dine path already does. `GET /triggers` (filter by `trigger_type` /
  `status`) replaces `GET /exceptions`. Generation stays catalog-driven: the `/generators` catalog advertises
  a neutral generate endpoint per generator (`POST /generators/{generator_id}/generate`, `generator_id` ∈
  `{wire, dine_in}`), replacing `/exceptions/generate` and `/tickets/generate`. Attachment bytes move under
  `GET /triggers/{trigger_id}/attachments/{attachment_id}`.

### D3 — Producers, consumers, and the webui follow the contract

- **Ingestor**: `IncomingTriggerRaisedEvent`, `IngestionRecord.{trigger_id, trigger_type, trigger_detail}`,
  `TriggerStoreClient.fetch_trigger`, `trigger_id_ctx` logging, queue `ingestor.trigger_raised.v1`, binding
  `trigger_source.trigger_raised.v1`, publishing `TriggerDispatchedEvent`.
- **Agent-runtime**: consume `TriggerDispatchedEvent`; `TriggerStoreClient`; `trigger_id_ctx`;
  `compute_idempotency_key(trigger_id, …)`; dispatch queue `agent-runtime.trigger_dispatched.v1`; reply
  events carry `trigger_id`; `Trace.correlation_id` defaults to `trigger_id`.
- **Notification-service**: bind the two new routing keys; `signal_mapper` maps the new event names.
- **Webui**: nav → `/triggers` "Triggers"; `features/exceptions/` → `features/triggers/`
  (`TriggersPage` / `TriggerDetailPage` / `TriggerSummary` / `GenerateTriggerButton`); `signalToKeys` maps
  `trigger_dispatched` and keys on `["trigger", id]`; the generated OpenAPI clients (`api/gen/*.ts`) are
  **regenerated** from the new backend schema, not hand-edited. The "TYPE" column still shows the domain
  discriminator value (`unable_to_apply`, `dine_in`) — that is data.
- **Compose / deploy**: service `stub-trigger-generator` (+ Dockerfile path), env prefix `STUBEXC_` →
  `STUBTRIG_`, `…_MONGO_COLLECTION` default `trigger_messages` (drop `…_TICKETS_COLLECTION`), the two moved
  queue names, and every service-name reference (`http://stub-trigger-generator:8081`).

### D4 — Migration: dev clean-slate, no back-compat

This is a breaking wire-contract + schema change and the platform is pre-production, single-tenant, and
seeded from immutable packs (operators already `down -v` to re-seed). Therefore **no dual-read, no
compat shims, no in-place data migration**: rename everything in one coordinated change and reset with
`docker compose … down -v`. As part of the sweep, ensure no stray domain-named trigger collections survive
(`exceptions`, `tickets`, `sample_exceptions`).

## Scope boundaries — what stays domain-specific (do **not** rename)

Reference-domain **data** is legitimately domain-named and is out of scope: the seed packs
(`wire-repair-standard`, `wire-repair-agentic`), `backend/docs/methodology/worked-examples/**`, the domain
MCP servers (`mcp_stub/servers/wire_transfer_exception`, `restaurant_dinein`), the stub's domain contract
modules and sample payloads, the domain trigger-artifact schema ids and their `SCHEMA_VERSION` values
(`pin.payments.wire_exception/1.0`, the dining one), and every domain field inside a payload
(`order_type`, `reason_codes`, `beneficiary`, …). Historical ADRs are **not** rewritten; this ADR is the
forward record. A docs/README vocabulary pass is a separate, lower-priority follow-up.

## Consequences

- The platform's inbound-payload plane is domain-neutral end to end: no `exception` term survives in
  platform code, wire contracts, event/queue vocabulary, the dev trigger source's service name or store, or
  the webui platform surface. A third (or nth) domain adds a generator + a pack — never a new collection or a
  vocabulary exception.
- One `trigger_messages` collection replaces two, with uniform fetch-back returning clean domain payloads —
  simpler storage, and the wire path gains the ADR-047 D1 metadata-stripping the dine path already had.
- Breaking change, taken deliberately at clean-slate: existing dev volumes and any external consumer bound to
  the old routing keys / schema literals must reset. Acceptable pre-production; captured here so it is a
  decision, not a surprise.
- The end-to-end reference flow (`tools/demo_wire_repair.sh`) and both reference packs must run green on the
  new vocabulary; the OpenAPI-generated webui clients regenerate cleanly.

## Design calls fixed by this ADR (change here, not in code review)

1. Producer-role routing-key segment is **`trigger_source`** (the stub is its dev implementation), not
   `stub_trigger` — so a real trigger source reuses the segment.
2. The stored inbound payload is a **wrapper** (`StoredTrigger.payload`), keeping the store domain-blind,
   rather than a flattened union of domain fields.
3. Fetch-back returns the **clean domain payload** for every domain (metadata stripped), unifying the wire
   and dine behaviours on the dine (ADR-047 D1) side.
4. **Clean-slate** migration — no back-compat — per D4.
