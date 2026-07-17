# Amendia — Services & Endpoints Reference

A catalogue of every service authored so far, the HTTP endpoints each exposes, and the RabbitMQ
events it publishes/consumes. All services are FastAPI apps following the same conventions
(config via `env_prefix`, `app.state` singletons, `/health`, structured logs). Messaging rides a
single **durable topic exchange `amendia.events`**; routing keys are `<service>.<event>.v1`,
built via `amendia_common.events.rk`.

## Service map

| Service | Port | Role | ADR |
|---|---|---|---|
| **stub-exception-generator** | 8081 | Dev/test stand-in for the bank's exception store: generates synthetic wire exceptions, persists them, publishes `exception_raised`, serves the fetch-back API. | ADR-007, ADR-012 |
| **ingestor** | 8082 | Consumes `exception_raised`, fetches the full envelope, records an ingestion, resolves it against the registry, dispatches to the runtime, and reconciles the runtime's reply. | ADR-008, ADR-011, ADR-012 |
| **agent-runtime** | 8083 | Executes a resolved pack as a compiled LangGraph process with schema-validated artifacts, Mongo checkpointing, and real human-in-the-loop approval gates. `llm` capabilities call a real, config-driven model (polyllm + ConfigForge — Bedrock/OpenAI/Gemini and **Nemotron via `nemoclaw`**, ADR-018, selectable per-capability or platform-wide); `mcp` falls back to simulation. **Execution mode** (`AGENTRT_EXECUTION_MODE`, ADR-017): `native` (default, in-process executor) or `nemoclaw` (routes `llm`/`mcp` capability execution through NemoClaw's OpenShell sandbox; Phase 1). Per-instance **capability memoization** (`AGENTRT_MEMOIZE_CAPABILITIES`, ADR-019) makes an interrupted node's reviewed artifact the committed one (no model re-invoke on HITL resume). In `nemoclaw` mode with `AGENTRT_CAPABILITY_WORKER_ENABLED`, capability execution is brokered to the **capability-worker** over RabbitMQ (ADR-020) — OpenShell has no inbound API. Supports a fourth capability kind **`deep_agent`** (ADR-021): a bounded Deep Agents loop inside one node, nemoclaw-only, HITL-gated, memoized. Read APIs for the catalog + instances/tasks. | ADR-009, ADR-011, ADR-012, ADR-016, ADR-017, ADR-018, ADR-019, ADR-020, ADR-021 |
| **capability-worker** (`agent-runtime/worker`) | — | The in-sandbox execution substrate (ADR-020). A plain RabbitMQ consumer (no HTTP port) that runs the shared execution core for one capability per job and publishes the correlated result: `llm` → `inference.local/v1`, real `mcp` via the in-sandbox registry, side-effect skills sandboxed (simulated in dev). Carries no Mongo/checkpoint/HITL — the host owns audit. Runs as a plain process in dev/CI; inside an OpenShell sandbox in prod. | ADR-020 |
| **process-registry** | 8084 | Authoring/write side: registers capabilities & artifact schemas, onboards + validates ProcessPacks, pins versions on activation, and answers the triage `/resolve` lookup. | ADR-010, ADR-012 |
| **identity** (`platform/identity`) | 8086 | Maps `(iss, sub)` → durable Amendia user, JIT-provisions on first login, stores role assignments, and serves the caller's identity (`/me`) + user/role admin. | ADR-012 |
| **keycloak** (dev IdP) | 8087 | OIDC identity provider for local dev (realm `amendia-dev`). Not an Amendia service — a standards-only dependency; in production this is the customer's own IAM. | ADR-012, ADR-013 |
| **notification-service** (`platform/notification-service`) | 8088 | Consumes the platform's domain events and fans them out to browsers over **SSE** as thin invalidation signals — the real-time transport behind the HITL dashboard (retires polling). Stateless, no DB, publishes nothing. | ADR-015 |
| **config-forge** (`platform/config-forge-service`) | 8040 | Platform config registry (Mongo DB `ConfigForge`). Stores provider-agnostic **LLM model profiles** (and future config kinds) addressed by canonical ref; the agent-runtime resolves them at call time via polyllm. Providers: `openai`/`google_genai`/`bedrock`/`nemoclaw` (Nemotron via NVIDIA NIM / OpenShell managed proxy, ADR-018). Secrets are stored as *references*, never values. | ADR-016, ADR-018 |

Shared libraries: **`amendia_common`** (exchange, `Service` enum, `rk()`, event-name constants),
**`amendia_contracts`** (the five contract models + `wire_exception` envelope + semver matcher),
**`amendia_bpmn`** (the shared BPMN 2.0 parser for the Iteration-1 subset),
**`amendia_auth`** (OIDC bearer validation → `Principal`, identity resolution → `AuthenticatedUser`,
and the FastAPI auth dependencies every service mounts).

The **webui** (React SPA) is the operator UI; it authenticates via OIDC (Authorization Code + PKCE)
and drives these endpoints with a bearer token — see ADR-013 and `Amendia_User_Guide.md`.

---

## Authentication & authorization (all services)

Every service mounts **`amendia_auth`**. The model (ADR-012): *authenticate with the IdP, authorize in
Amendia* — only `iss`/`sub` (+ email/name for display) are trusted from tokens; roles come from the
identity service, never from vendor claims.

- **Baseline:** every endpoint requires a valid OIDC bearer **except `/health`**. A missing/invalid token
  → **401** with `WWW-Authenticate: Bearer` (the token is never echoed). Reads need only an authenticated
  principal (no role).
- **Role guards** (403, naming the missing role): process-registry **mutations** (pack submit / bpmn /
  validate / activate / deprecate, capability & artifact-schema register/deprecate) require
  `role.process.owner`; identity **admin** endpoints require `role.platform.admin`.
- **Identity from the token, not the body:** agent-runtime `claim`/`decide` derive the acting user from
  the bearer (→ identity service). The existing domain checks (task-role ∈ the caller's roles, SoD by
  `amendia_user_id`, `allowed_decisions`, claim ownership) run on that resolved identity; `decided_by` /
  `assignee` / `actor_log` store the Amendia `usr-…` id.
- **Service-to-service** calls (ingestor → registry `/resolve`, runtime → registry catalog reads,
  runtime/ingestor → stub fetch-back) carry a shared **`X-Amendia-Internal`** token instead of a user
  bearer (the `principal_or_internal` dependency). Broker-driven flows are unaffected (no HTTP).
- **`AGENTRT_AUTH_*` / `<PREFIX>_AUTH_*` config** per service: `issuer`, `audience`, `jwks_uri`
  (internal JWKS URL — the compose dev-networking escape hatch), `identity_base_url`, `internal_token`,
  and `auth_disabled` (tests/local only). Dev tokens come from Keycloak (`:8087`); see
  `backend/deploy/keycloak/README.md`.

---

## Deployment

- **Dev:** `backend/deploy/docker-compose.yml` is the dev/CI substrate (unchanged). `native` mode by
  default; opt into the `nemoclaw` profile for the capability-worker + stubs.
- **Prod:** a **portable umbrella Helm chart** at `deploy/helm/amendia/` (ADR-022) — generic base +
  thin per-provider values overlays (`values-gke.yaml` first-class; `values-eks/aks/onprem.yaml`
  scaffolded). Cloud specifics (storageClass, GPU nodeSelector/tolerations, ingress class, pod identity)
  live only in overlays behind `# per-provider` seams. Secrets via **Vault (Kubernetes auth)** —
  `deploy/vault/` — no plaintext anywhere (realizes ADR-016 `literal:→vault:`). Nemotron serving is a
  single `inference.mode` toggle (`nim-selfhosted` | `nvidia-hosted` | `bedrock-only`). Egress is
  **default-deny + per-service allowlists** (the worker's AMQP→RabbitMQ rule resolves ADR-020's
  `[confirm]`). Prod runs `nemoclaw` fail-closed. Install: `helm upgrade --install amendia
  deploy/helm/amendia -n amendia -f deploy/helm/amendia/values-gke.yaml`.

---

## 1. stub-exception-generator (`:8081`)

Plays the bank's exception store for local dev, honouring the real event + fetch-back contract.
`generate` needs an authenticated principal; the fetch-back reads also accept the internal token
(the runtime/ingestor call them service-to-service).

| Method | Path | Description |
|---|---|---|
| `POST` | `/exceptions/generate` | Generate N synthetic *unable-to-apply* wire exceptions (optional `reason_code`, `amount`, `currency`, `include_attachments`, `count`), persist them, and publish an `exception_raised` event each. Returns the created items + their routing keys. |
| `GET` | `/exceptions` | List stored exceptions (filterable by `exception_type`, `status`, `reason_code`, `limit`, `offset`). |
| `GET` | `/exceptions/{exception_id}` | Fetch the full stored envelope — the **fetch-back** endpoint consumers call. 404 if unknown. |
| `GET` | `/exceptions/{exception_id}/attachments/{attachment_id}` | Stream a canned attachment's bytes with its media type. |
| `GET` | `/health` | Liveness/readiness (mongo + rabbit). |

**Events** — publishes `stub_exception.exception_raised.v1` (thin: identity + `fetch_url`).

## 2. ingestor (`:8082`)

Entry point of the consumer side. Records each exception, then drives the dispatch lifecycle
(`received → dispatched → accepted/rejected`, or terminal `no_process`).

| Method | Path | Description |
|---|---|---|
| `GET` | `/ingestions` | List ingestion-log records (filterable by `exception_type`, `status`, `limit`, `offset`). Records carry `status`, `status_history`, `resolution`, `process_instance_id`, `no_match`, `rejection`. |
| `GET` | `/ingestions/{exception_id}` | Fetch one ingestion record. 404 if unknown. |
| `GET` | `/health` | Liveness/readiness (mongo + rabbit consumer). |

**Events** — consumes `stub_exception.exception_raised.v1`, and the runtime replies
`agent_runtime.dispatch_accepted.v1` + `agent_runtime.dispatch_rejected.v1`. Publishes
`ingestor.exception_dispatched.v1` (contract 4) on a registry match.

## 3. agent-runtime (`:8083`)

Executes the resolved process. HTTP surface = catalog **reads** (mirrors of the registry-owned
collections) + instance/task reads + the **HITL decision API**. Execution itself is event-driven.

### Process instances

| Method | Path | Description |
|---|---|---|
| `GET` | `/instances` | List process instances (filter by `exception_id`, `status`). |
| `GET` | `/instances/{process_instance_id}` | Instance + status + `outcome` + artifact names + `actor_log` + links to its HITL tasks. 404 if unknown. |
| `GET` | `/instances/{process_instance_id}/state` | The current **checkpointed graph state** (artifacts, actor_log, trace) — dev/debug surface, guarded by `AGENTRT_ENABLE_DEBUG_API`. |

### HITL tasks (the human approval gates)

| Method | Path | Description |
|---|---|---|
| `GET` | `/hitl-tasks` | List tasks (filter by `status`, `role`, `process_instance_id`, `exception_id`). |
| `GET` | `/hitl-tasks/{task_id}` | Fetch one task (payload artifacts, proposed_actions, `sod.excluded_users`, `allowed_decisions`). 404 if unknown. |
| `POST` | `/hitl-tasks/{task_id}/claim` | Claim a task — **no body**; the actor is the bearer's resolved identity. 409 unless `open`; 403 if SoD-excluded or the task's role ∉ the caller's roles. |
| `POST` | `/hitl-tasks/{task_id}/decide` | Decide — body `{decision, comment?, edits?, approved_action_ids?}` (identity from the bearer). Enforces claim ownership + allowed-decisions + SoD, re-validates `edit_and_approve` edits against the pinned schema, then resumes the graph. |

### Inbound messages (ADR-031)

| Method | Path | Description |
|---|---|---|
| `POST` | `/messages` | Deliver an inbound business message — body `{message_name, exception_id?\|correlation_id?, payload?}` (exactly one business anchor). Correlates by anchor + `message_name` to a parked instance and resumes it exactly once. Guarded by `principal_or_internal` (external systems / `mcp_stub` use `X-Amendia-Internal`; an operator may use a bearer). Responses: `202` delivered, `404` no_matching_subscription (buffered for the ordering race), `409` already_consumed, `422` invalid payload (a declared output artifact that fails its pinned schema is never committed). |

### Catalog reads (mirror of registry-owned collections)

| Method | Path | Description |
|---|---|---|
| `GET` | `/packs` · `/packs/{key}` · `/packs/{key}/{version}` | List / versions / one ProcessPack manifest. |
| `GET` | `/packs/{key}/{version}/bpmn` | The pack's BPMN XML (`application/xml`). |
| `GET` | `/capabilities` · `/capabilities/{id}` · `/capabilities/{id}/{version}` | List / versions / one capability descriptor. |
| `GET` | `/artifact-schemas` · `/artifact-schemas/{key}` · `/artifact-schemas/{key}/{version}` | List / versions / one artifact schema. |
| `POST` | `/admin/seed` | Idempotently load the local seed dataset (guarded by `AGENTRT_ENABLE_SEED_API`; the registry is the real write owner). |
| `GET` | `/health` | Liveness/readiness. |

**Events** — consumes `ingestor.exception_dispatched.v1`. Publishes, all `agent_runtime.*.v1`:
`dispatch_accepted`, `dispatch_rejected`, `hitl_task_created`, `hitl_task_decided`,
`hitl_task_expired` (SLA breach → escalated), `timer_fired`, `message_received`, `process_completed`,
`process_failed`. In `nemoclaw` mode also publishes `agent_runtime.capability_exec_request.v1` (job →
capability-worker) and awaits the correlated `capability_exec_result` reply (ADR-020).

**Execution conformance level (ADR-034).** `AGENTRT_EXECUTION_PROFILE` selects the BPMN conformance
level: **`common_executable`** (default — parallel gateways, timers + **SLA timer boundaries**, error
boundaries, inbound messages + event-based gateways, embedded sub-processes, the full task set) or the
conservative **`common_subset`**. A pack's minimum level is **derived from its BPMN** at activation and
pinned in the resolution sidecar (`required_execution_profile`); the runtime refuses a pack it can't run
at **load** (not mid-flight) with a distinct `pack_requires_profile` dispatch-rejection reason. Retired
granular values (`parallel`/`timers`/…) normalize to `common_executable`.

**Durable timer poller.** A lifespan task (`AGENTRT_TIMER_POLL_SECONDS`, default 15s) wakes on due
timers in the Mongo `timers` collection and resumes the parked instance — no delayed-message broker;
crash-safe (re-fires anything due on restart). This is what makes an SLA `due_at` **fire**.

## 4. process-registry (`:8084`)

The authoring/write side — the only writer of `capabilities`, `artifact_schemas`, `process_packs`.
No messaging in v1; validation only (no BPMN execution).

**Auth:** every **mutation** below (capability/schema register+deprecate, pack submit/bpmn/validate/
activate/deprecate, and the **onboarding** session transitions + `introspect-mcp`) requires
**`role.process.owner`**. Reads, `/resolve`, and `/roles` accept any authenticated principal **or** the
shared internal token — the runtime reads the catalog, the ingestor calls `/resolve` service-to-service,
and the admin UI reads `/roles`.

### Triage

| Method | Path | Description |
|---|---|---|
| `POST` | `/resolve` | Map an envelope to a pinned pack — body `{envelope}` → `{pack_key, pack_version, rule_id, resolved_at}`; 404 `NoMatchResponse` when nothing matches. Principal-or-internal (the ingestor calls it with `X-Amendia-Internal`). |

### Roles (ADR-026)

| Method | Path | Description |
|---|---|---|
| `GET` | `/roles` | Roles **in use** across active packs — `[{role_id, label?, description?, sources[]}]`. Ids are **derived** from every active pack's bindings (`hitl.role` + human `executor.role`); `sources` are the `pack_key@version` packs referencing each id; `label`/`description` come from the optional per-pack `pack_roles` sidecar (authored on the onboarding Policies step) or are `null`. **A read** — principal-or-internal, no owner gate. The admin role picker builds its assignable list from this (merged with the two code-fixed platform roles on the frontend). Does **not** surface `role.process.owner` / `role.platform.admin` — those are a frontend constant. |

### Onboarding (form-driven, ADR-025)

The `OnboardingSession` state machine — a registry-owned authoring *scratch* doc (`onboarding_sessions`,
owner-scoped). Every transition returns the full session (the webui wizard renders it). **Staging, not
writing:** new artifacts/capabilities live on the session and are written to the catalog only at `commit`.
All owner-gated.

| Method | Path | Description |
|---|---|---|
| `POST` | `/capabilities/introspect-mcp` | Introspect a running MCP server — body `{endpoint, transport?, headers?, domain}` → each tool with its schemas + a **compliance verdict**. Owner-gated, `http(s)`-only, timeout-bounded (SSRF surface). 502 on connection failure. |
| `POST` | `/onboarding` | Create a session (`initiated`) — body basics. 409 if `pack_key@version` is already an active/deprecated pack. |
| `GET` | `/onboarding` · `/onboarding/{id}` | List this owner's sessions / resume one. |
| `DELETE` | `/onboarding/{id}` | Abandon (204) — safe; nothing was written to the catalog. |
| `PUT` | `/onboarding/{id}/bpmn` | Parse BPMN, derive inventory (exclusive gateways only). |
| `POST` | `/onboarding/{id}/capabilities` | Stage `mcp` capabilities (+ two inferred artifacts each, MCP-only) and reused catalog refs. |
| `PUT` | `/onboarding/{id}/bindings` | Store bindings — checks the task↔binding bijection and the side-effect→HITL coupling (field-level errors). |
| `PUT` | `/onboarding/{id}/triage` · `.../policies` | Triage predicate trees / gateway variables + SoD + pack-local roles. `policies` also accepts optional `role_meta` (label/description per role id) → written to the `pack_roles` sidecar at commit and surfaced by `GET /roles` (ADR-026). |
| `POST` | `/onboarding/{id}/assemble` | Compose the manifest + **dry-run** the 7-stage validator against staged rows; returns the report. |
| `POST` | `/onboarding/{id}/commit` | Ordered, idempotent chain (artifacts → capabilities → pack draft → BPMN → validate → activate); stops before activate on a non-clean report; re-run is a no-op → `completed`. |

### Capabilities

| Method | Path | Description |
|---|---|---|
| `POST` | `/capabilities` | Register a capability descriptor (201; immutable version → 409 on conflict). |
| `GET` | `/capabilities` · `/capabilities/{id}` · `/capabilities/{id}/{version}` | List / versions / one descriptor. |
| `POST` | `/capabilities/{id}/{version}/deprecate` | Mark a version deprecated. |

### Artifact schemas

| Method | Path | Description |
|---|---|---|
| `POST` | `/artifact-schemas` | Register an artifact schema (draft 2020-12 meta-validated; 201). |
| `GET` | `/artifact-schemas` · `/artifact-schemas/{key}` · `/artifact-schemas/{key}/{version}` | List / versions / one registration. |
| `POST` | `/artifact-schemas/{key}/{version}/deprecate` | Mark a version deprecated. |

### ProcessPacks (lifecycle: `draft → validated → active → deprecated`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/packs` | Submit a pack manifest as `draft` (201). |
| `PUT` | `/packs/{key}/{version}/bpmn` | Upload/replace the BPMN (recomputes sha; drops the pack back to `draft`). |
| `POST` | `/packs/{key}/{version}/validate` | Run the 7-stage cross-contract validator; `validated` iff clean. |
| `POST` | `/packs/{key}/{version}/activate` | Re-validate + pin every capability/artifact range to an exact version + write the resolution sidecar; sets `active`. |
| `POST` | `/packs/{key}/{version}/deprecate` | Mark the pack deprecated. |
| `GET` | `/packs` · `/packs/{key}` · `/packs/{key}/{version}` | List / versions / one manifest. |
| `GET` | `/packs/{key}/{version}/bpmn` | The BPMN XML (`application/xml`). |
| `GET` | `/packs/{key}/{version}/validation-report` | The stored validation report sidecar. |
| `GET` | `/packs/{key}/{version}/resolution` | The pinned resolution sidecar (capabilities/artifacts/bindings) — how the runtime loads a pack without re-resolving. |
| `GET` | `/health` | Liveness/readiness. |

## 5. identity (`:8086`)

The keystone that keeps RBAC IdP-agnostic and audit durable: `(iss, sub)` → a durable
`amendia_user_id`, JIT-provisioned on first login, with role assignments stored in Amendia. Owns the
`users` (re-keyable `identities: [{iss, sub}]` array) and `role_assignments` collections. No messaging.
Consumes `amendia_auth` itself, but resolves locally (it never HTTP-calls its own resolve endpoint).

| Method | Path | Description |
|---|---|---|
| `POST` | `/internal/resolve-principal` | **Internal only** (`X-Amendia-Internal`). Body `{iss, sub, email?, name?}` → `{amendia_user_id, email, display_name, status, roles}`. JIT-provisions an unknown identity (status from `IDENTITY_JIT_DEFAULT_STATUS`) and materialises staged role assignments — attaching them attributed to whoever staged them, then **deleting the pending rows** so they don't linger; refreshes stored email/name if changed. Called by `amendia_auth`'s `CurrentUser`. |
| `GET` | `/me` | Bearer-authenticated. The caller's Amendia user + roles — the webui's identity source. 403 `user_disabled` if disabled. |
| `GET` | `/users` | **Admin** (`role.platform.admin`). List users (filter by `status`, `role`; pagination). |
| `GET` | `/users/{amendia_user_id}` | **Admin.** One user + roles. 404 if unknown. |
| `POST` | `/users/{amendia_user_id}/roles` | **Admin.** Assign a `role.*` — body `{role}` (201; 409 if already held; 422 if the role fails the `role.*` pattern). |
| `DELETE` | `/users/{amendia_user_id}/roles/{role}` | **Admin.** Revoke a role (404 if the user lacks it). Guardrails: **409 `self_protection`** if an admin revokes their own `role.platform.admin`; **409 `last_admin`** if it would leave zero active platform admins (re-checked at operation time and rolled back). |
| `POST` | `/users/{amendia_user_id}/disable` · `/enable` | **Admin.** Flip `status` (a disabled user resolves with `status: disabled` → 403 at every enforcing service). Disable guardrails: **409 `self_protection`** (can't disable your own account); **409 `last_admin`** (can't disable the last active platform admin — status is rolled back). |
| `GET` | `/pending-role-assignments` | **Admin.** List staged (pending) access, aggregated per email; optional case-insensitive `email` substring filter. Each entry is `{email, roles[], staged_by, staged_at}`. **Invariant:** a row is listed only for an email that has **not** signed in yet — emails now belonging to a provisioned user are filtered out (their roles are already live on the user). |
| `POST` | `/pending-role-assignments` | **Admin.** Stage roles for an email — body `{email, roles[]}` (201; **422** if any role fails the `role.*` pattern; **409 `user_exists`** if the email already belongs to a provisioned user — the response carries that user's `amendia_user_id` so the UI redirects to their detail). |
| `PUT` | `/pending-role-assignments/{email}` | **Admin.** Replace the full staged-role set for an email (same **409 `user_exists`** guard as `POST`). |
| `DELETE` | `/pending-role-assignments/{email}` | **Admin.** Remove staged access (204; 404 if none staged). |
| `GET` | `/health` | Liveness/readiness (mongo). |

The admin user-detail responses (`GET /users`, `GET /users/{id}`, and the mutating admin
endpoints) additionally carry `role_details: [{role, assigned_by, assigned_at}]`; `/me` omits it.

Identity assigns any well-formed `role.*` (no catalog check). The admin UI's *pickable* role list is
sourced separately from the registry's `GET /roles` (§4, ADR-026); identity stays the assignment authority.

**Seeding** (`IDENTITY_SEED_ON_STARTUP=true`): role assignments are seeded **by email** and materialised
onto the user on first login — riya → `role.payments.ops_analyst`, marcus → `role.payments.ops_approver`,
priya → `role.process.owner` + `role.platform.admin`, alex → `role.platform.admin`. sam is seeded with
**no** roles (his first login exercises the roleless state). No brittle Keycloak UUIDs — Amendia users are
born only by JIT (nothing is written to Mongo until first sign-in). Seeding **skips any email already
provisioned** (so restarts don't resurrect a Pending-tab row for someone who has signed in), and every
startup runs a **reconcile** that purges pending rows whose email now belongs to a provisioned user
(self-heals legacy strays; no migration needed).

## 6. notification-service (`:8088`)

Stateless real-time fan-out relay (ADR-015): consumes the platform's domain events from `amendia.events`
and pushes **thin invalidation signals** to connected browsers over **Server-Sent Events**, so the webui's
live surfaces update in real time instead of polling. No database; **publishes nothing**.

| Method | Path | Description |
|---|---|---|
| `GET` | `/stream` | **SSE** (`text/event-stream`). Bearer-authenticated (any valid token — **no role**); 401 without one. Emits an initial `event: ready`, then `data:` signal frames, with a `: ping` heartbeat every ~20s. One long-lived connection per browser tab. |
| `GET` | `/health` | Liveness/readiness; `ready` reflects the RabbitMQ consumer connection, plus a `subscribers` count. |

**Events** — consumes via a **per-instance `exclusive`, `auto_delete` broadcast queue** (so every replica
receives *every* matching event — not a shared work-queue): `agent_runtime.{hitl_task_created,
hitl_task_decided,process_completed,process_failed,dispatch_accepted}.v1`, `ingestor.exception_dispatched.v1`,
`stub_exception.exception_raised.v1`. Publishes nothing.

**Signal shape (the security boundary)** — each SSE frame carries only `{type, exception_id?,
process_instance_id?, task_id?, element_id?, role?, outcome?}` — ids/labels only, **never** payload data
(`decision`, `comment`, `edits`, `trace`, `reason`, capability outputs). The browser uses a signal only to
decide which cached queries to invalidate, then re-fetches the actual data through the existing role-guarded
REST endpoints. Consequences: the broadcast stream needs **authentication only** (no per-event role checks),
and a missed/duplicated/replayed signal can never leak or corrupt data.

**Auth note:** browser `EventSource` can't send an `Authorization` header, so the webui consumes `/stream`
via a `fetch`-based reader that carries the bearer and mirrors the API client's `401 → renew → reconnect`
cycle. Proxied at `/api/notifications` (nginx sets a long `proxy_read_timeout` for the long-lived stream).

## 7. keycloak (dev IdP, `:8087`)

Not an Amendia service — the OIDC provider for local dev, standing in for the customer's IAM. Imports the
committed realm `amendia-dev` (`backend/deploy/keycloak/`): public PKCE-S256 client `amendia-webui`, a
dev-only confidential `amendia-dev-cli` for curl token-minting, a per-client `amendia-api` audience mapper,
users riya/marcus/priya/**alex**/**sam** (`dev-password`) — alex is platform-admin-only (proves the
admin-only nav) and sam has no staged roles (first login lands in the roleless state) — and **zero persona
roles** (roles live in Amendia). Standard OIDC
surface only — discovery `/.well-known/openid-configuration`, `/protocol/openid-connect/{auth,token,certs}`.
Issuer: `http://localhost:8087/realms/amendia-dev`. See the realm README for the dev-networking footgun
(services validate `iss` against the browser-facing issuer but fetch JWKS via the internal alias).

## 8. config-forge (`:8040`)

Platform config registry (FastAPI + Mongo DB `ConfigForge`). Stores config entries — today, provider-agnostic
**LLM model profiles** (polyllm `ModelProfile`s) — addressed by a canonical ref
`{env}.{kind}[.{provider}][.{platform}].{name}`. The agent-runtime resolves a profile at call time via
polyllm's `RemoteConfigLoader`. **Secrets are stored as references (`env:` / `file:` / `literal:`), never
values.** Configure/rotate models here with **no code change or redeploy** — see the
[LLM configuration guide](../amendia_llm_configuration_guide.md) and **ADR-016**.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/config/resolve/{ref}` | **The polyllm lookup** — resolves a canonical ref to the config entry (`.data` = ModelProfile). 404 if unknown. |
| `GET` | `/config/?kind=llm` | List entries (optional `env`/`kind`/`provider`/`platform` filters). |
| `POST` | `/config/` | Create an entry (`env`, `kind`, `name`, `data`, …); ref is built from the segments. 409 on duplicate ref. |
| `PUT` | `/config/{id}` | Update `data`/`description` in place — the mutable path for rotating a model/key. |
| `DELETE` | `/config/{id}` | Remove an entry. |
| `GET` | `/healthz` | Liveness. |

No auth today (platform-internal); seed defaults with `scripts/seed.py`.

---

## End-to-end flow (how the endpoints + events chain)

0. The operator (or the demo script) obtains an OIDC bearer from Keycloak (`:8087`); every HTTP call
   below carries it. Service-to-service hops carry `X-Amendia-Internal` instead.
1. `POST :8081/exceptions/generate` (bearer) → persists + publishes `exception_raised`.
2. ingestor consumes it, `GET :8081/exceptions/{id}` (fetch-back, internal token), records `received`,
   then `POST :8084/resolve` (internal token) → on match records `dispatched` + publishes
   `exception_dispatched`.
3. agent-runtime consumes `exception_dispatched`, loads the pack from the registry
   (`GET :8084/packs/.../{manifest,resolution,bpmn}` + capabilities/schemas, internal token), creates an
   instance, publishes `dispatch_accepted` (→ ingestor records `accepted`), and runs the compiled graph.
   Each `llm` capability resolves its model profile from config-forge (`GET :8040/config/resolve/{ref}`)
   and calls the real provider via polyllm; `mcp` falls back to simulation.
4. At each human gate the runtime publishes `hitl_task_created`; an operator drives
   `POST :8083/hitl-tasks/{id}/claim` then `/decide` (bearer — identity from the token, `CurrentUser`
   resolved via `:8086/internal/resolve-principal`) to resume the graph. `decided_by` records the
   Amendia `usr-…` id.
5. On completion the instance is `completed` with `process_completed` published; inspect via
   `GET :8083/instances/{id}` and `GET :8083/instances/{id}/state`.

**Real-time fan-out (ADR-015):** every event published in steps 1–5 (`exception_raised`,
`exception_dispatched`, `dispatch_accepted`, `hitl_task_created`/`decided`, `process_completed`/`failed`) is
also consumed by the **notification-service** (`:8088`) and pushed to connected dashboards over SSE as a thin
signal; the webui invalidates the matching queries and re-fetches through the REST endpoints above — so the
UI reflects each transition live, without polling.

The `tools/demo_wire_repair.sh` script exercises exactly this chain — it mints riya/marcus bearers from
Keycloak and passes them throughout (analyst gates as riya, approver gates as marcus).
