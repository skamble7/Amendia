# Amendia

**Amendia is a generic, domain-neutral, agentic process-execution platform.** You give it a
**BPMN 2.0 process** (as data) and a set of **capabilities** (MCP tools / LLM steps that connect to
your systems); it **executes the process faithfully**, step by step — pausing at the human approval
gates you defined, validating every artifact against a pinned schema, and recording an immutable,
observable audit trail.

The platform does not know your domain. It is deployed **on the customer's infrastructure, typically
one instance per department** (effectively single-tenant per deployment). Onboarding a new process is
**data, not code**: you register BPMN definitions, capabilities, artifact schemas, and triage rules —
you do not write new platform code.

The **wire-transfer payment-exception** flow is the *reference example* shipped for local dev and
testing (the `stub-exception-generator` + `ingestor` path). It is one worked domain on top of a
generic engine — not the product's boundary. No `exception` / `wire` / `payment` term is hardcoded in
platform code (ADR-047 domain neutrality); those appear only as configured data.

---

## Core model

```
BPMN process   →  what happens, in what order, with which gates
Capabilities   →  how each automated step is executed (MCP tool or LLM)
Artifact schemas → the pinned shape of every value produced or consumed
Triage rules   →  which process governs an incoming trigger (attribute-based predicate tree)
ProcessPack    →  a versioned, validated, pinned bundle of the above, activated for real traffic
```

The runtime **compiles** an annotation-free BPMN diagram + the pack manifest + the pinned capability
resolution into a **LangGraph `StateGraph`** (native interpretation — no external BPMN engine, ADR-011
/ ADR-027). A process instance is a **Mongo-checkpointed thread** (a checkpoint per node boundary =
the audit trail). Human gates use LangGraph `interrupt`/`resume`.

### Controls the platform enforces by construction

A side-effectful capability cannot run without a human authorization gate (`≥ approve_actions`); the
preparer cannot approve their own work (four-eyes / separation-of-duties, per-instance); a gateway may
only branch on a `required`, upstream-produced field; every artifact write is validated against its
pinned schema; packs are immutable and version-pinned at activation; the runtime refuses a pack whose
profile it cannot run. These remove the "someone forgot a control" risk class. What the platform
cannot know — that the *right* steps were automated, that a capability does exactly what it claims,
that someone accountable accepted the risk — is the job of the **methodology** (see
`backend/docs/methodology/amendia_operating_model.md`).

---

## Services

All custom services publish on host ports in the **`18xxx`** band (remapped +10000 out of the
contended `80xx` band); the **container-internal** port is the historical `80xx`. Keycloak and all
infra keep their standard ports.

| Service | Host port | Container | Role |
|---|---|---|---|
| **config-forge** | 18040 | 8040 | Platform config registry; serves provider-agnostic LLM `ModelProfile`s (polyllm) by canonical ref |
| **stub-exception-generator** | 18081 | 8081 | Dev/test stub that *plays the bank's exception store*: fabricates a synthetic exception, persists it, publishes a thin `exception_raised` event, serves fetch-back + attachments |
| **ingestor** | 18082 | 8082 | Consumes `exception_raised`, fetches the full payload, resolves it to a pack via the registry `POST /resolve`, dispatches to the runtime, tracks the ingestion lifecycle |
| **agent-runtime** | 18083 | 8083 | The execution engine: compiles BPMN→LangGraph, runs capabilities, validates artifact writes, owns the HITL task/approval lifecycle (claim/decide with SoD) |
| **process-registry** | 18084 | 8084 | Authoring / write side: registers capabilities, artifact schemas, and packs; runs the multi-stage cross-contract validator; drives the pack lifecycle; answers triage `/resolve`; hosts the onboarding **copilot** (ADR-052) |
| **webui** | 18085 | 8085 | React SPA: exception queue, process/instance visualization, approval inbox, registry/onboarding, GLEA views (PKCE sign-in) |
| **identity** | 18086 | 8086 | `(iss,sub)` → Amendia user + roles; JIT provisioning; role admin. Authorization lives here, not in IdP claims |
| **keycloak** | 8087 | 8080 | Dev IdP; committed `amendia-dev` realm (PKCE public client, `amendia-api` audience). Stands in for the customer IdP |
| **notification-service** | 18088 | 8088 | Consumes `amendia.events`, fans out thin invalidation signals to browsers over SSE (real-time HITL dashboard) |
| **glea-service** | 18090 | 8090 | GLEA audit system-of-record: consumes governed events, persists append-only into ClickHouse, serves audit / explainability / lineage read-models (ADR-058) |

### Infrastructure

| Component | Port(s) | Purpose |
|---|---|---|
| MongoDB 7 | 27017 | Exceptions, packs, capabilities, artifact schemas, instances, HITL tasks, config |
| RabbitMQ 3 | 5672 / 15672 | `amendia.events` durable topic exchange (the seam between services); management UI (guest/guest) |
| ClickHouse 24.8 | 8123 / 9001→9000 | Single store for OTel traces + logs **and** the GLEA audit system-of-record |
| OpenTelemetry Collector | 4317 / 4318 | Single OTLP aggregation point; every service + sandbox exports here → ClickHouse (ADR-058) |

---

## Shared libraries (`libs/`)

| Package | Contents |
|---|---|
| `amendia_contracts` | The five platform contracts (ProcessPack, Capability, Artifact schema, Dispatch event, HITL task) + `VersionedRef` / semver matching. The exact models the runtime executes |
| `amendia_bpmn` | BPMN 2.0 parsing / validation of the supported subset (shared by registry validation and runtime compilation) |
| `amendia_auth` | OIDC resource-server library: `TokenValidator` → `Principal`; FastAPI deps (`current_principal`, `require_roles`, `principal_or_internal`) |
| `amendia_common` | Shared vocabulary + event helpers (`events.rk(tenant, service, event)` builds canonical routing keys) |
| `amendia_telemetry` | OTel conventions + setup (semantic-attribute constants, span/log helpers) — ADR-058 |
| `polyllm` | Provider-agnostic LLM abstraction (ModelProfiles resolved via ConfigForge) |

---

## Repository layout

```
Amendia/
├── backend/
│   ├── deploy/                 # docker-compose.yml (full local stack), keycloak realm, otel collector config
│   ├── docs/                   # all documentation (see backend/docs/README.md)
│   │   ├── adr/                #   architecture decision records (ADR-007 … current)
│   │   ├── methodology/        #   the onboarding methodology (start: amendia_operating_model.md)
│   │   ├── reference/          #   platform contracts, services reference, execution pipeline
│   │   ├── operations/         #   user / admin / auth / operator guides
│   │   ├── engineering/        #   build plans, backlogs, audits
│   │   └── _build-prompts/     #   Claude Code build prompts kept for provenance
│   └── services/               # agent-runtime, ingestor, process-registry, platform/{config-forge,glea,identity,notification}
├── libs/                       # amendia_contracts, amendia_bpmn, amendia_auth, amendia_common, amendia_telemetry, polyllm
├── webui/                      # React SPA (Vite dev server on 5173; nginx image on 18085)
├── stub_exception_generator/   # the reference "bank exception store" stub
├── mcp_stub/                   # MCP server stub(s) for capability transport testing
├── tools/                      # demo + operator scripts (e.g. demo_wire_repair.sh)
└── deploy/                     # helm chart + vault (portable k8s deployment, ADR-022)
```

---

## Quickstart (local dev)

Brings up Mongo, RabbitMQ, ClickHouse, the OTel Collector, Keycloak, and all Amendia services. The
process-registry seeds and health-gates so downstream consumers start only once its state is ready.

```bash
docker compose -f backend/deploy/docker-compose.yml up --build

# Seed the default LLM profiles into ConfigForge (once)
docker compose -f backend/deploy/docker-compose.yml run --rm config-forge \
  python scripts/seed.py --mongo-uri mongodb://mongodb:27017 --db ConfigForge --env dev

# Generate one reference exception (via the stub)
curl -s -X POST localhost:18081/exceptions/generate \
  -H 'content-type: application/json' -d '{"count":1}' | jq

# Health checks
curl -s localhost:18084/health   # process-registry (ready ⇒ seed onboarded)
curl -s localhost:18083/health   # agent-runtime
curl -s localhost:18090/health   # glea-service
```

> Editing the seed (BPMN / manifest / capabilities / schemas) changes immutable, already-onboarded
> versions — bring the stack down with a fresh volume first:
> `docker compose -f backend/deploy/docker-compose.yml down -v`.

The webui dev server runs on **5173** (`cd webui && npm run dev`) and proxies `/api/<service>` to the
`18xxx` backends. The composed nginx image is browsable at **18085**. Sign-in is Authorization Code +
PKCE against Keycloak (8087); seeded dev users are **riya** (ops analyst), **marcus** (ops approver),
and **priya** (process owner + platform admin). Authorization is resolved in Amendia's identity
service, never parsed from IdP token claims.

### End-to-end reference flow

`tools/demo_wire_repair.sh` drives the full path: generate → ingest → resolve → dispatch → accept →
run (through the human approval gates, with SoD blocking self-approval) → `completed`, then shows the
produced artifacts via `GET /instances/{id}/state`.

---

## Execution modes

- **`native`** (default) — capabilities run in the agent-runtime's in-process executor.
- **`nemoclaw`** (ADR-017 / ADR-020, `--profile nemoclaw`) — capability execution routes to an
  in-sandbox **capability-worker** that consumes jobs off RabbitMQ and publishes results (the host
  never calls into the sandbox; egress-only). LLM capabilities go through **polyllm + ConfigForge**;
  MCP capabilities are self-descriptive on `runtime.endpoint` (ADR-024).

---

## Observability & audit (GLEA — ADR-058)

**G**overnance, **L**ineage, **E**xplainability, **A**udit run on OpenTelemetry + ClickHouse. Every
service and sandbox exports traces + logs to a single OTel Collector; `glea-service` additionally
consumes governed domain events and persists them append-only as the audit **system-of-record**,
serving per-instance audit-trail, decision-trail explainability, and cross-instance lineage
read-models to the webui instance view.

---

## Documentation

- **Front door:** `backend/docs/methodology/amendia_operating_model.md` — the lifecycle, roles, and gates.
- **Pitch:** `backend/docs/amendia_project_brief.md`.
- **Contracts & services:** `backend/docs/reference/` (five platform contracts, services reference, execution pipeline).
- **Decisions:** `backend/docs/adr/` (numbered, chronological).
- **Doc map:** `backend/docs/README.md`.
