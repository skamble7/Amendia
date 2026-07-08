# Amendia — Services & Endpoints Reference

A catalogue of every service authored so far, the HTTP endpoints each exposes, and the RabbitMQ
events it publishes/consumes. All services are FastAPI apps following the same conventions
(config via `env_prefix`, `app.state` singletons, `/health`, structured logs). Messaging rides a
single **durable topic exchange `amendia.events`**; routing keys are `<tenant>.<service>.<event>.v1`,
built via `amendia_common.events.rk`.

## Service map

| Service | Port | Role | ADR |
|---|---|---|---|
| **stub-exception-generator** | 8081 | Dev/test stand-in for the bank's exception store: generates synthetic wire exceptions, persists them, publishes `exception_raised`, serves the fetch-back API. | ADR-007 |
| **ingestor** | 8082 | Consumes `exception_raised`, fetches the full envelope, records an ingestion, resolves it against the registry, dispatches to the runtime, and reconciles the runtime's reply. | ADR-008, ADR-011 |
| **agent-runtime** | 8083 | Executes a resolved pack as a compiled LangGraph process with schema-validated artifacts, Mongo checkpointing, and real human-in-the-loop approval gates. Read APIs for the catalog + instances/tasks. | ADR-009, ADR-011 |
| **process-registry** | 8084 | Authoring/write side: registers capabilities & artifact schemas, onboards + validates ProcessPacks, pins versions on activation, and answers the triage `/resolve` lookup. | ADR-010 |

Shared libraries: **`amendia_common`** (exchange, `Service` enum, `rk()`, event-name constants),
**`amendia_contracts`** (the five contract models + `wire_exception` envelope + semver matcher),
**`amendia_bpmn`** (the shared BPMN 2.0 parser for the Iteration-1 subset).

---

## 1. stub-exception-generator (`:8081`)

Plays the bank's system for local dev — no auth, but it honours the real event + fetch-back contract.

| Method | Path | Description |
|---|---|---|
| `POST` | `/exceptions/generate` | Generate N synthetic *unable-to-apply* wire exceptions (optional `tenant`, `reason_code`, `amount`, `currency`, `include_attachments`, `count`), persist them, and publish an `exception_raised` event each. Returns the created items + their routing keys. |
| `GET` | `/exceptions` | List stored exceptions (filterable by `tenant`, `exception_type`, `status`, `reason_code`, `limit`, `offset`). |
| `GET` | `/exceptions/{exception_id}` | Fetch the full stored envelope — the **fetch-back** endpoint consumers call. 404 if unknown. |
| `GET` | `/exceptions/{exception_id}/attachments/{attachment_id}` | Stream a canned attachment's bytes with its media type. |
| `GET` | `/health` | Liveness/readiness (mongo + rabbit). |

**Events** — publishes `<tenant>.stub_exception.exception_raised.v1` (thin: identity + `fetch_url`).

## 2. ingestor (`:8082`)

Entry point of the consumer side. Records each exception, then drives the dispatch lifecycle
(`received → dispatched → accepted/rejected`, or terminal `no_process`).

| Method | Path | Description |
|---|---|---|
| `GET` | `/ingestions` | List ingestion-log records (filterable by `tenant`, `exception_type`, `status`, `limit`, `offset`). Records carry `status`, `status_history`, `resolution`, `process_instance_id`, `no_match`, `rejection`. |
| `GET` | `/ingestions/{exception_id}` | Fetch one ingestion record. 404 if unknown. |
| `GET` | `/health` | Liveness/readiness (mongo + rabbit consumer). |

**Events** — consumes `*.stub_exception.exception_raised.v1`, and the runtime replies
`*.agent_runtime.dispatch_accepted.v1` + `*.agent_runtime.dispatch_rejected.v1`. Publishes
`<tenant>.ingestor.exception_dispatched.v1` (contract 4) on a registry match.

## 3. agent-runtime (`:8083`)

Executes the resolved process. HTTP surface = catalog **reads** (mirrors of the registry-owned
collections) + instance/task reads + the **HITL decision API**. Execution itself is event-driven.

### Process instances

| Method | Path | Description |
|---|---|---|
| `GET` | `/instances` | List process instances (filter by `tenant`, `exception_id`, `status`). |
| `GET` | `/instances/{process_instance_id}` | Instance + status + `outcome` + artifact names + `actor_log` + links to its HITL tasks. 404 if unknown. |
| `GET` | `/instances/{process_instance_id}/state` | The current **checkpointed graph state** (artifacts, actor_log, trace) — dev/debug surface, guarded by `AGENTRT_ENABLE_DEBUG_API`. |

### HITL tasks (the human approval gates)

| Method | Path | Description |
|---|---|---|
| `GET` | `/hitl-tasks` | List tasks (filter by `tenant`, `status`, `role`, `process_instance_id`, `exception_id`). |
| `GET` | `/hitl-tasks/{task_id}` | Fetch one task (payload artifacts, proposed_actions, `sod.excluded_users`, `allowed_decisions`). 404 if unknown. |
| `POST` | `/hitl-tasks/{task_id}/claim` | Claim a task — body `{user_id, role?}`. 409 unless `open`; 403 if SoD-excluded or role mismatch. |
| `POST` | `/hitl-tasks/{task_id}/decide` | Decide — body `{user_id, decision, comment?, edits?, approved_action_ids?}`. Enforces claim + allowed-decisions + SoD, re-validates `edit_and_approve` edits against the pinned schema, then resumes the graph. |

### Catalog reads (mirror of registry-owned collections)

| Method | Path | Description |
|---|---|---|
| `GET` | `/packs` · `/packs/{key}` · `/packs/{key}/{version}` | List / versions / one ProcessPack manifest. |
| `GET` | `/packs/{key}/{version}/bpmn` | The pack's BPMN XML (`application/xml`). |
| `GET` | `/capabilities` · `/capabilities/{id}` · `/capabilities/{id}/{version}` | List / versions / one capability descriptor. |
| `GET` | `/artifact-schemas` · `/artifact-schemas/{key}` · `/artifact-schemas/{key}/{version}` | List / versions / one artifact schema. |
| `POST` | `/admin/seed` | Idempotently load the local seed dataset (guarded by `AGENTRT_ENABLE_SEED_API`; the registry is the real write owner). |
| `GET` | `/health` | Liveness/readiness. |

**Events** — consumes `*.ingestor.exception_dispatched.v1`. Publishes, all `<tenant>.agent_runtime.*.v1`:
`dispatch_accepted`, `dispatch_rejected`, `hitl_task_created`, `hitl_task_decided`,
`process_completed`, `process_failed`.

## 4. process-registry (`:8084`)

The authoring/write side — the only writer of `capabilities`, `artifact_schemas`, `process_packs`.
No messaging in v1; validation only (no BPMN execution).

### Triage

| Method | Path | Description |
|---|---|---|
| `POST` | `/resolve` | Map an envelope to a pinned pack — body `{tenant, envelope}` → `{pack_key, pack_version, rule_id, resolved_at}`; 404 `NoMatchResponse` when nothing matches. |

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

---

## End-to-end flow (how the endpoints + events chain)

1. `POST :8081/exceptions/generate` → persists + publishes `exception_raised`.
2. ingestor consumes it, `GET :8081/exceptions/{id}` (fetch-back), records `received`, then
   `POST :8084/resolve` → on match records `dispatched` + publishes `exception_dispatched`.
3. agent-runtime consumes `exception_dispatched`, loads the pack from the registry
   (`GET :8084/packs/.../{manifest,resolution,bpmn}` + capabilities/schemas), creates an instance,
   publishes `dispatch_accepted` (→ ingestor records `accepted`), and runs the compiled graph.
4. At each human gate the runtime publishes `hitl_task_created`; an operator drives
   `POST :8083/hitl-tasks/{id}/claim` then `/decide` to resume the graph.
5. On completion the instance is `completed` with `process_completed` published; inspect via
   `GET :8083/instances/{id}` and `GET :8083/instances/{id}/state`.

The `tools/demo_wire_repair.sh` script exercises exactly this chain.
