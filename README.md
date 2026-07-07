# ASTRA

**ASTRA** (Agentic System for Traceable Reasoning and Artifacts) is a composable framework for structured intelligence. Artifact kinds, capabilities, and capability packs come together to define, extend, and orchestrate what a platform can produce — enabling systems to dynamically evolve without changing platform code.

---

## Core Concepts

### Artifact Kind

An artifact kind is a declarative template that defines what type of knowledge a platform can produce. It acts as the canonical contract describing the shape, semantics, and representations of an artifact.

| Property | Purpose |
|---|---|
| `_id` | Globally unique identifier (`cam.<category>.<kind>`) |
| `title`, `category`, `aliases`, `status` | Human-friendly metadata and lifecycle state |
| `schema_versions.json_schema` | Exact structure and required fields of the artifact |
| `schema_versions.prompt` | Canonical prompt contract for agents that generate this kind |
| `schema_versions.depends_on` | Upstream kinds needed to generate this kind |
| `schema_versions.diagram_recipes` | Embedded diagram definitions (Mermaid, etc.) |
| `schema_versions.narratives_spec` | Human-readable narrative specifications |

Naming: `cam.<category>.<name>` — e.g. `cam.agile.user_story`, `cam.architecture.service_contract`

### Capability

A capability is a declarative, globally addressable unit of execution. It defines what it produces, what inputs it accepts, and how it runs — either via an MCP tool or an LLM.

| Property | Description |
|---|---|
| `id` | Stable identifier, e.g. `cap.cobol.copybook.parse` |
| `execution` | `McpExecution` (HTTP/STDIO + tool name) or `LlmExecution` (ConfigForge LLM ref) |
| `produces_kinds` | Artifact kind IDs this capability outputs |
| `parameters_schema` | JSON Schema for dynamic user-supplied parameters |

Naming: `cap.<group>.<action>` — e.g. `cap.data.fetch`, `cap.diagram.mermaid`

### Capability Pack

A capability pack is a versioned, goal-oriented bundle of capabilities. It declares which capabilities run, in what order, and with what inputs — transforming a raw capability library into a purpose-driven workflow.

```
Artifact kinds  →  define what can be produced
Capabilities    →  define how to produce them
Capability Packs →  define why and when to produce them
```

Each pack contains one or more **playbooks** — ordered sequences of steps, each referencing a capability. The AI agent interprets this blueprint and handles execution, dependency resolution, enrichment, and persistence.

---

## Services

### Artifact Service (port 9020)

A pure kind-registry and schema service. Key features:

- **Kind registry API** — list, retrieve, validate, and manage artifact kind definitions
- **Category API** — manage high-level artifact categories
- **Build envelope** — validate and compute natural key + fingerprint for an artifact payload (`POST /registry/build-envelope`)
- Seeded at startup with built-in kind definitions; no RabbitMQ dependency

### Workspace Manager Service (port 9027)

Owns all runtime workspace artifact storage and workspace lifecycle management. Key features:

- **Create / upsert / batch upsert** artifacts with computed fingerprints and natural keys (delegates schema validation to artifact-service via `POST /registry/build-envelope`)
- **List, retrieve, patch, replace** with ETag-based optimistic concurrency
- **Version history** and soft-delete
- **Workspace lifecycle** — consumes `platform.workspace.created/updated/deleted` events from RabbitMQ to maintain workspace parent documents
- Publishes events on artifact creation and update

### Capability Service (port 9021)

Manages capabilities, pack inputs, and capability packs. Key features:

- Full CRUD for `GlobalCapability` documents with tag/kind/mode search
- Pack management including publish (makes pack immutable and available for runs)
- Pack inputs CRUD and effective input contract resolution
- Resolved pack view — capabilities expanded inline, used by conductor during orchestration

### Conductor Service (port 9022) — Agent Runtime

Orchestrates **runs** of a capability pack's playbook. It accepts a `StartRunRequest`, records the run, and executes it using a LangGraph agent built from **conductor-core** nodes.

**LLM Architecture:**

- **Agent LLM** (`CONDUCTOR_LLM_CONFIG_REF`) — used by `mcp_input_resolver` and `narrative_enrichment`
- **Execution LLM** — per-capability `llm_config_ref` resolved from ConfigForge at runtime
- Set `OVERRIDE_CAPABILITY_LLM=1` to force all capabilities to use the conductor's agent LLM

**Run API:** `POST /runs/start` — returns immediately with `run_id`; execution runs as a background task.

### Planner Service (port 9025) — Intent-Driven Planning and Execution

The entry point for conversational, intent-driven capability runs. Accepts a natural-language user intent, selects capabilities, builds a plan, and executes it using the same conductor-core nodes.

See [Planner Service](#planner-service-detail) below for full details.

### Capability Onboarding Service (port 9026)

A stateless wizard backend for registering new MCP servers as ASTRA capabilities. No database or message broker — the entire wizard state travels as a progressive JSON document.

**4-step flow:**

1. **Connect server** — discovers tools via `tools/list`
2. **Select tool** — pick one tool (auto-selected for single-tool servers)
3. **Review & edit** — LLM infers capability ID, name, tags, and artifact kind schema
4. **Register** — creates the artifact kind and capability in the respective services

---

## conductor-core (Shared Execution Library)

`libs/conductor-core` contains all core execution logic shared between the conductor-service and planner-service. It is structured into six packages:

| Package | Contents |
|---|---|
| `conductor_core.models` | Shared Pydantic models: `PlaybookRun`, `StepState`, `ArtifactEnvelope`, `StartRunRequest`, etc. |
| `conductor_core.nodes` | Six reusable LangGraph execution nodes (see below) |
| `conductor_core.llm` | polyllm-backed `AgentLLM` / `ExecLLM` protocols and factories |
| `conductor_core.mcp` | MCP transport client (`MCPConnection`, `MCPTransportConfig`) |
| `conductor_core.protocols` | Structural protocols for `RunRepository`, `ArtifactServiceClient` (registry reads), `WorkspaceManagerClient` (artifact writes), `EventPublisher` |
| `conductor_core.artifacts` | `ArtifactAdapter` utilities for normalising staged artifacts |

### Execution Nodes

| Node | Description |
|---|---|
| `capability_executor_node` | Central router: manages step index, three-phase transitions, publishes lifecycle events |
| `mcp_input_resolver_node` | Builds MCP tool arguments; discovers live input schema via `tools/list`; validates with LLM repair |
| `mcp_execution_node` | Connects to MCP server, invokes tool, handles retries and pagination, stages artifacts |
| `llm_execution_node` | Resolves `llm_config_ref`, builds prompt from kind schema + upstream artifacts, validates JSON output |
| `diagram_enrichment_node` | Calls `cap.diagram.mermaid` after each step to attach Mermaid diagrams (non-fatal) |
| `narrative_enrichment_node` | Calls agent LLM to generate Markdown narratives from artifact JSON (non-fatal) |
| `persist_run_node` | Normalises staged artifacts and calls `workspace-manager-service /artifact/{workspace_id}/upsert-batch`; records final run status |

### Three-Phase Step Execution

Each playbook step runs across three phases:

```
discover  →  enrich (diagram)  →  narrative_enrich  →  advance
```

Enrichment failures are non-fatal; discovery failures terminate the run immediately.

---

## Planner Service Detail

### Session Lifecycle

```
planning → awaiting_clarification → planning → awaiting_inputs
  → ready_to_execute → executing → completed | failed
```

### Planner Agent (LangGraph)

Runs per user message turn. Nodes:

```
session_init → intent_resolver → capability_selector → plan_builder
                                                             ↓
                                              confidence ≥ 0.65?
                                            yes ↓           no ↓
                                       plan_approved    clarification
```

- **`intent_resolver`** — extracts structured intent (type, entities, constraints, confidence)
- **`capability_selector`** — matches capabilities from the manifest cache using LLM ranking
- **`plan_builder`** — builds ordered steps with LLM-prefilled `run_inputs`
- **`clarification`** — asks user a question when confidence is too low

### Two-Step Execute Flow (ADR-006)

1. **`POST /plan/approve`** — locks the plan; returns `input_form_type` (`"structured"` or `"freetext"`) and `prefilled_inputs` with the live MCP input schema. Does **not** start execution.
2. **`POST /run`** — accepts user-confirmed `run_inputs` and starts the execution agent as a background task.

### HTTP API

| Method | Path | Description |
|---|---|---|
| `POST` | `/sessions` | Create a new session |
| `GET` | `/sessions/{id}` | Fetch session state |
| `POST` | `/sessions/{id}/messages` | Send a user message |
| `GET` | `/sessions/{id}/plan` | Get current plan steps |
| `PATCH` | `/sessions/{id}/plan` | Edit plan steps |
| `POST` | `/sessions/{id}/plan/approve` | Lock plan; return input form metadata |
| `POST` | `/sessions/{id}/run` | Submit confirmed inputs; start execution |
| `GET` | `/sessions/{id}/runs/{run_id}` | Get run status |

### WebSocket API

`GET /ws/sessions/{session_id}` — per-session event stream with cursor-based replay.

| Event | Trigger |
|---|---|
| `planner.response` | Planning turn complete |
| `plan.approved` | Plan locked |
| `execution.started` | Run accepted |
| `execution.run_created` | PlaybookRun created |
| `execution.completed` / `execution.failed` | Run finished |

Step-level events (`step.started`, `step.completed`, etc.) travel via RabbitMQ → notification-service → workspace WebSocket.

---

## MCP Server Authoring

To register an MCP server as an ASTRA capability, your server must follow these rules.

### Tool Design

Follow a **1:1:1** mapping:

```
one MCP tool  →  one ASTRA capability  →  one artifact kind
```

Each tool should do one well-scoped thing and return one type of structured output.

### Return Types

Always annotate your tool's return type with a typed Pydantic model. FastMCP generates the `outputSchema` from your return annotation — a generic `Dict[str, Any]` produces a useless schema.

```python
class RainaInputDoc(BaseModel):
    inputs: InputsBlock

@mcp.tool(name="raina.input.fetch")
async def raina_input_fetch(stories_url: str) -> RainaInputDoc:
    ...
```

### Transport

ASTRA communicates over **streamable-http**. Configure your server to listen on HTTP:

```python
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8003
MCP_MOUNT_PATH=/mcp
```

### Authentication

Use ASTRA's alias-based auth — store the env var **name**, not the value. Supported methods:

| Method | Field | Example |
|---|---|---|
| Bearer token | `alias_token` | `MY_SERVICE_TOKEN` |
| Basic auth | `alias_user` / `alias_password` | `MY_SVC_USER` / `MY_SVC_PASS` |
| API key | `alias_key` | `MY_API_KEY` |

### Schema Validation

ASTRA validates every tool response at runtime against the JSON schema stored in the artifact kind registry. A response that fails validation is silently dropped — no artifact is persisted.

### Pre-Registration Checklist

- [ ] Return type is a typed Pydantic model (not `Dict[str, Any]`)
- [ ] Tool returns the same shape on every call
- [ ] Server is reachable at `<base_url>/mcp` via streamable-http
- [ ] Output schema in the Inspect step matches your actual return structure
- [ ] Artifact kind JSON schema in the Review step accurately describes your output
- [ ] End-to-end tested before registering

### Runtime Behaviour After Registration

1. Conductor connects to your server at the URL in `execution.transport`
2. The configured tool is called with resolved input arguments
3. Response is validated against the registered artifact kind JSON schema
4. On success: artifact is persisted and available to downstream capabilities
5. On failure: step is marked failed; no artifact is written

---

## Key Environment Variables

### Conductor Service

| Variable | Description |
|---|---|
| `CONDUCTOR_LLM_CONFIG_REF` | ConfigForge ref for the agent LLM |
| `CONFIG_FORGE_URL` | ConfigForge service URL |
| `OVERRIDE_CAPABILITY_LLM` | `1` to force all capabilities to use the conductor's LLM |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | Provider keys for capability LLMs |
| `ARTIFACT_SVC_BASE_URL` | `http://astra-artifact-service:9020` — kind registry reads |
| `WORKSPACE_MGR_BASE_URL` | `http://astra-workspace-manager-service:9027` — workspace artifact writes |

### Planner Service

| Variable | Default | Description |
|---|---|---|
| `PLANNER_LLM_CONFIG_REF` | — | ConfigForge ref for planner + narrative LLM |
| `CONFIG_FORGE_URL` | — | ConfigForge service URL |
| `CAPABILITY_SVC_BASE_URL` | `http://astra-capability-service:9021` | Capability service |
| `ARTIFACT_SVC_BASE_URL` | `http://astra-artifact-service:9020` | Artifact service (kind registry) |
| `WORKSPACE_MGR_BASE_URL` | `http://astra-workspace-manager-service:9027` | Workspace manager service (artifact storage) |
| `DIAGRAM_MCP_BASE_URL` | `http://host.docker.internal:8001` | Diagram MCP server |
| `MONGO_URI` | — | MongoDB connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for manifest cache |
| `RABBITMQ_URI` | — | RabbitMQ AMQP URI |

---

## Service Ports

| Service | Port |
|---|---|
| artifact-service | 9020 |
| capability-service | 9021 |
| conductor-service | 9022 |
| planner-service | 9025 |
| capability-onboarding-service | 9026 |
| workspace-manager-service | 9027 |

---

## Documentation

- [ASTRA Framework Overview](docs/astra_wiki.md)
- [Planner Service Reference](docs/planner_service.md)
- [MCP Server Authoring Guide](docs/mcp-authoring-guide.md)

---

## Amendia — Stub Exception Generator

Amendia is a generic, agentic payment-exception-handling platform for banks. The
[stub exception generator](stub_exception_generator/) is a dev/test stub that **plays the bank's
exception store**: on demand it fabricates a synthetic wire-transfer "unable-to-apply" exception,
persists it to MongoDB, and publishes a thin `exception_raised` event to the `amendia.events`
RabbitMQ topic exchange (routing key e.g. `bank-alpha.stub_exception.exception_raised.v1`). It also
serves the full exception document and attachment bytes back over HTTP, so downstream services can
fetch details from the `fetch_url` in the event. See `backend/docs/amendia_project_brief.md` and
`backend/docs/wire-transfer-exception-reference.md`.

Bring up mongo + rabbitmq + the stub, generate an exception, and fetch it back:

```bash
docker compose -f backend/deploy/docker-compose.yml up --build

# Generate one exception (all body fields optional; count max 20)
curl -s -X POST localhost:8081/exceptions/generate \
  -H 'content-type: application/json' -d '{"count":1}' | jq

# Fetch the full stored document back (use the exception_id from the response)
curl -s localhost:8081/exceptions/EXC-2026-XXXXXX | jq

# Fetch one of its attachments
curl -s localhost:8081/exceptions/EXC-2026-XXXXXX/attachments/att-1 --output screen.png
```
