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
│   │   ├── docker-compose.yml     # Local dev: backend + mongo + rabbitmq + keycloak + identity (+ webui)
│   │   ├── docker-compose.auth-strict.yml  # Override: turn OFF the compat-stub bridges (full enforcement)
│   │   └── keycloak/              # Committed amendia-dev realm export + integration README
│   │
│   ├── docs/                      # Architecture notes, ADRs, sample BPMN files
│   │
│   ├── libs/                      # Shared Python packages (repo-root libs/: amendia_common,
│   │   ├── domain/                # amendia_contracts, amendia_bpmn, amendia_auth)
│   │   ├── bpmn/                  # BPMN 2.0 parsing/validation utilities
│   │   ├── auth/                  # OIDC bearer validation → Principal; identity resolution; FastAPI deps
│   │   └── clients/               # Bank API clients + internal service-to-service clients
│   │
│   └── services/                  # Each service is an ASGI (FastAPI) app or worker
│       ├── ingestion/             # RabbitMQ event consumer; fetches exception details + files via bank API
│       ├── process-registry/      # Stores BPMN process definitions + exception→process registry (CRUD APIs)
│       ├── agent-runtime/         # Executes resolved processes via LangGraph agents; owns orchestration
│       │                          # and human-in-the-loop task states (design is a separate scope — stub the boundary)
│       └── platform/              # Cross-cutting platform services
│           ├── identity/          # (iss,sub) → Amendia user + roles; JIT provisioning; role admin (:8086)
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

## Agent Runtime — foundation (implemented)

`backend/services/agent-runtime/` is a FastAPI service (port **8083**) that establishes the platform's
**five contracts** (see `amendia_platform_contracts_v1.md`) as first-class, persisted, validated
models, with a seeded `wire-repair-standard` process pack. This is the **foundation** — models +
storage + seed + read APIs; it does not itself execute. Execution (LangGraph compilation, capability
execution, dispatch consumers, HITL resume) arrived in the next slice — see the **Agent Runtime —
execution** section below and **ADR-011**. See **ADR-009** and `backend/services/agent-runtime/README.md`
for the foundation.

The five contracts (`app/models/`): (1) ProcessPack manifest, (2) Capability descriptor, (3) Artifact
schema registration, (4) Dispatch event + accepted/rejected replies, (5) HITL task/approval — plus a
runtime-owned `process_instance` aggregate. References between them use a `VersionedRef` value type
(`<id>@<range-or-pin>`); `oneOf`s are discriminated unions (executor, capability runtime, recursive
triage predicate); self-contained invariants are enforced, while cross-document checks are deferred to
the registry. Events build routing keys via `amendia_common.events.rk` (this work added
`Service.INGESTOR` / `Service.AGENT_RUNTIME` to the shared lib).

Persistence is one MongoDB collection per aggregate under natural keys (immutable versions; duplicate
insert → 409): `process_packs`, `capabilities`, `artifact_schemas`, `process_instances`, `hitl_tasks`,
`dispatch_log`. An **idempotent seed loader** validates every file, meta-validates each artifact
`json_schema` (draft 2020-12), injects the real `bpmn_sha256`, and upserts by natural key (CLI,
`POST /admin/seed`, or startup auto-seed).

**Endpoints (read-only):** `GET /packs`, `/packs/{key}/{version}`, `/packs/{key}/{version}/bpmn`
(`application/xml`), `/capabilities[/{id}/{version}]`, `/artifact-schemas[/{key}/{version}]`,
`/instances`, `/hitl-tasks`, `POST /admin/seed`, `GET /health`. No authoring APIs — pack/capability/
schema authoring belongs to the process-registry service.

## Process Registry (implemented — v1)

`backend/services/process-registry/` is a FastAPI service (port **8084**) — the **authoring/write side**
of the platform (build plan Step 2). It registers capabilities and artifact schemas, onboards
ProcessPacks through the full **cross-contract validator**, drives the pack lifecycle with version
pinning at activation, and answers the runtime triage lookup (`POST /resolve`). No UI, no BPMN
*execution* — validation only. See **ADR-010** and `backend/services/process-registry/README.md`.

**Shared contract models.** To validate exactly what the runtime executes, the five contract models were
extracted into `libs/amendia_contracts` (with a `semver` range matcher); agent-runtime keeps thin
re-export shims so its imports/tests are unchanged.

**Ownership split.** The registry is the **write owner** of the `capabilities`, `artifact_schemas`, and
`process_packs` collections; the **agent-runtime reads** them. Registry-only data (validation reports,
activation resolutions) lives in sidecar collections so the shared pack doc stays a pure manifest.

**Lifecycle:** `draft → validated → active → deprecated`. `POST /packs` (draft) → `PUT .../bpmn` →
`POST .../validate` (all-clear ⇒ `validated`) → `POST .../activate` (pins ranges to exact versions) →
`.../deprecate`. Versions are immutable; a BPMN re-upload drops the pack to `draft`.

**Validator (7 stages):** BPMN subset/well-formedness → binding↔task bijection → capability resolution
(in-range, active) → HITL & side-effect policy (`side_effectful` ⇒ ≥ `approve_actions`; binding ≥
capability `min_hitl_mode`) → artifact/IO compatibility → gateway-variable satisfaction → SoD/triage.
Findings are `{code, severity, element_id?, path?, message}`; any error keeps the pack out of `validated`.

**Seeding through the front door:** `python -m app.seeding.onboard_seed` drives the seed dataset through
the real APIs (schemas → capabilities → manifest → BPMN → validate → activate) — the validator's
end-to-end proof (the seed passes clean). `REGISTRY_SEED_ON_STARTUP=true` in compose.

**Key endpoints:** `POST /capabilities`, `POST /artifact-schemas`, `POST /packs`, `PUT
/packs/{k}/{v}/bpmn`, `POST /packs/{k}/{v}/{validate,activate,deprecate}`, `GET` reads +
`/validation-report` + `/resolution`, `POST /resolve`, `GET /health`.

## Agent Runtime — execution (implemented)

The agent-runtime now **executes** a resolved pack end-to-end, turning the dormant dispatch/HITL
lifecycle live. One stub-generated exception flows automatically to a completed process instance,
through capability execution, schema-validated artifact writes, and **real human approval gates operated
via API**, all checkpointed in Mongo. Capabilities run in **simulation mode** (deterministic, no external
LLM/MCP calls) behind a real executor seam. See **ADR-011** and `backend/services/agent-runtime/README.md`.

- **Ingestor now resolves + dispatches.** After `received`, it calls the registry `POST /resolve`:
  match → `dispatched` + publishes `exception_dispatched`; 404 → the new terminal `no_process`; registry
  down → stays `received` for a retry sweep. It consumes the runtime's replies to reach `accepted`/`rejected`
  (all transitions guarded/idempotent).
- **Compile-don't-embed.** A shared BPMN parser (`libs/amendia_bpmn`, lifted from the registry so both
  validate the same subset) plus the manifest bindings and pinned resolution compile into a **LangGraph
  `StateGraph`**; the process instance is a checkpointed thread (checkpoint per node boundary = audit
  trail). Exclusive gateways become conditional edges over a small expression subset; parallel gateways are
  rejected (the seed BPMN was linearized).
- **Generic task runner + executor seam.** Per node: gather inputs → optional pre-gate → execute (kind
  dispatch: skill / llm / mcp, simulation-routed) → validate outputs against the **pinned** artifact schema
  → optional post-gate → commit + `actor_log`. Retries honour idempotency; the 10 wire-repair capabilities
  are deterministic and envelope-aware.
- **Real HITL.** Gates use LangGraph `interrupt`/`resume`; the engine materializes a `HitlTask` (mode-derived
  `allowed_decisions`, pinned-schema snapshots, `proposed_actions`, and **SoD `excluded_users` computed from
  `distinct_actor` policies × the actor_log**). `POST /hitl-tasks/{id}/claim` and `/decide` enforce the
  lifecycle, SoD (at claim **and** decide), the decisions table, and `edit_and_approve` re-validation, then
  resume the graph. Instances complete/fail with thin `process_completed`/`process_failed` events.
- **Executable proof:** `tools/demo_wire_repair.sh` drives generate → ingest → resolve → dispatch → accept →
  run (all four HITL modes, SoD blocking self-approval) → `completed`; `GET /instances/{id}/state` shows the
  artifacts. Nodes are pure/synchronous (the Mongo checkpointer is sync); all IO and human-gate handling
  live in the async engine, which also recovers `running` instances from their checkpoint on restart.

**New/changed endpoints:** ingestor unchanged surface (records now carry `resolution`,
`process_instance_id`, `no_match`, `rejection`); agent-runtime `POST /hitl-tasks/{id}/claim`,
`POST /hitl-tasks/{id}/decide`, enriched `GET /instances/{id}`, `GET /instances/{id}/state` (flag-guarded).

## Authentication & Authorization (implemented — backend + frontend)

Real OIDC authentication replaces the dev sign-in stub (three hardcoded users) and the agent-runtime
role-claim stub, end to end — backend enforcement **and** the webui PKCE sign-in. **Governing principle:
authenticate with the IdP, authorize in Amendia** — only `iss`/`sub` (+ email/name) are trusted from
tokens; roles come from Amendia's own store. Single deployment = one customer = one issuer. See
**ADR-012** (backend) and **ADR-013** (frontend), the normative `amendia_auth_architecture.md`, and
`backend/deploy/keycloak/README.md`.

- **Keycloak dev IdP (`:8087`)** with a committed `amendia-dev` realm (`backend/deploy/keycloak/`):
  PKCE-S256 public client `amendia-webui`, a dev-only CLI client for curl token-minting, an `amendia-api`
  audience mapper, users riya/marcus/priya, and **zero persona roles** (roles live in Amendia). The realm
  export doubles as the customer IdP-integration reference (issuer + PKCE client + audience are the only
  three things a customer's IAM team provides).
- **`libs/amendia_auth`** — shared resource-server library: a `TokenValidator` (discovery→JWKS, TTL cache
  with key-rotation refresh, RS/ES-only so `alg:none`/HS\* are rejected, `iss`/`aud`/`exp`) yielding a
  `Principal`; FastAPI deps `current_principal` / `current_user` (→ `AuthenticatedUser` with a 30s resolve
  cache) / `require_roles` / `principal_or_internal`. Env-prefixed config per service (`AGENTRT_AUTH_*`,
  …); an `auth_disabled` flag for tests.
- **Identity service (`platform/identity`, `:8086`)** — the keystone that keeps RBAC IdP-agnostic and audit
  durable. `users` (with a re-keyable `identities:[{iss,sub}]` array) + `role_assignments`; **JIT
  provisioning** on first login; internal `POST /resolve-principal` (shared-token guarded), `GET /me`, and
  `role.platform.admin`-guarded user/role admin. Role assignments are **seeded by email and materialised on
  first login** (riya→ops_analyst, marcus→ops_approver, priya→process.owner+platform.admin) — no brittle
  Keycloak UUIDs.
- **Enforcement** across all four services: baseline principal on every endpoint (except `/health`);
  **agent-runtime `claim`/`decide` drop the `{user_id, role}` body** and run the existing domain checks
  (task-role match, SoD, `allowed_decisions`, ownership) on the token-resolved identity —
  `decided_by`/`assignee` now store `amendia_user_id`; **process-registry mutations require
  `role.process.owner`**. Service-to-service calls carry a shared `X-Amendia-Internal` token. No service
  parses any vendor claim (`realm_access`/`groups`).
- **Webui (`oidc-client-ts` + `react-oidc-context`)** — Authorization Code + PKCE; "Continue with your
  organization" is the only sign-in path (the dev user-switcher is retired). A `/auth/callback` route
  restores the pre-login deep link; every API call carries the bearer, a 401 silent-renews then retries
  (full sign-in on failure), a 403 is surfaced (role / SoD), and identity + roles come from `GET /me` (never
  parsed from the token). Role-aware nav hides Registry for non-owners. Sign-out is RP-initiated (ends the
  IdP session). See `Amendia_User_Guide.md`.
- **Fully enforced by default.** The temporary compat bridge that let the pre-PKCE webui work has been
  **removed** (settings, code paths, compose flags, and the strict-override file are gone); the stack is
  strict out of the box.
- **Acceptance:** `tools/demo_wire_repair.sh` mints real Keycloak bearers and drives the wire-repair flow
  with **no identity in any body** (analyst=riya, approver=marcus); unauthenticated → 401, wrong role / SoD
  → 403, and `decided_by` on the immutable records shows Amendia `usr-…` ids.

**New services/ports:** Keycloak `:8087`, identity `:8086`. **New endpoints:** identity
`POST /internal/resolve-principal`, `GET /me`, `GET/POST/DELETE /users…`, `GET /health`.

## Current Scope

- Scaffold the monorepo per the structure above (Python workspace rooted at `backend/`, npm project at `webui/`).
- ~~Implement the stub exception generator (synthetic exceptions → MongoDB + RabbitMQ events).~~ **Done** — see the Stub Exception Generator section above and ADR-007.
- Implement ingestion (**done — basic**, see the Ingestor section and ADR-008), process-registry (**done — v1**, see the Process Registry section and ADR-010), config-forge, and notifications as mounted FastAPI sub-apps.
- ~~Stub the agent-runtime boundary (queue consumer skeleton only); its internal design is a separate upcoming scope.~~ **Done** — the foundation (contract models, persistence, `wire-repair-standard` seed; ADR-009) and now **execution** (LangGraph compilation, capability execution, dispatch consumers, HITL resume; ADR-011) are both in place. One exception runs end-to-end to a `completed` instance with real API-driven approval gates — see the two Agent Runtime sections above.
- ~~Authentication & authorization (replace the dev sign-in stub).~~ **Done** — OIDC end to end: `amendia_auth` + the identity service + Keycloak with enforcement/stub-removal across all services (ADR-012), and the webui PKCE sign-in with `/me`-driven identity (the dev user-switcher and the temporary compat bridge are gone; the stack is strict by default). See the Authentication & Authorization section above and `Amendia_User_Guide.md`.
- docker-compose for local dev: backend (single container), MongoDB, RabbitMQ, Keycloak, identity, webui.

## Open Questions (do not decide unilaterally — flag for discussion)

- ~~Whether the agent runtime embeds an existing BPMN engine (e.g., Camunda 8/Zeebe, Flowable) with agents as service-task workers, or interprets BPMN 2.0 natively with LangGraph driving execution.~~ **Resolved by ADR-011** — **native interpretation**: the runtime compiles the annotation-free BPMN + manifest + pinned resolution into a LangGraph `StateGraph` (no external BPMN engine), with the instance as a Mongo-checkpointed thread and HITL via `interrupt`/`resume`. (Parallel gateways, timers, and compensation remain out of the supported subset for now.)
- ~~Exact registry matching semantics (exception type only vs. attribute-based rules).~~ **Resolved by ADR-010** — attribute-based via a declarative predicate tree (`all/any/not/leaf` over envelope dot-paths), priority-ordered across active packs, evaluated identically in pack validation and `/resolve`. (Tenant-specific rule overrides remain a later question.)
- ~~Event schema/contract for exception events and the bank API interface shape.~~ **Resolved by ADR-007** for the `exception_raised` event + fetch-back API (as implemented by the stub); the real bank-connector interface may still differ and can map into this same envelope/contract.
