# ADR-009 — Agent-runtime foundation: contract models, persistence & seed data

- **Status:** Accepted (foundation slice)
- **Date:** 2026-07-07
- **Related:** `backend/docs/amendia_platform_contracts_v1.md` (the five contracts — source of truth);
  `backend/docs/wire-transfer-exception-reference.md` (BPMN §7, bindings §6, envelope §4);
  ADR-007 (stub / `exception_raised`), ADR-008 (ingestor); `backend/services/agent-runtime/README.md`.
- **Advances:** the "stub the agent-runtime boundary" item in `amendia_project_brief.md`.

## Context

The ingestor (ADR-008) records exceptions but has nowhere to hand them: there is no runtime that
knows how to execute a bank's exception-handling procedure. Before any execution can be built, the
platform's **five contracts** — the shapes that connect the (future) process-registry and the agent
runtime — need to exist as enforced, persisted, first-class citizens, and there needs to be a
concrete, internally-consistent dataset (the `wire-repair-standard` pack) to develop and test against.

This ADR covers the **foundation only**: contract models + MongoDB persistence + a seed dataset +
read APIs. It deliberately excludes execution.

## Decision

Introduce **`backend/services/agent-runtime/`**, a FastAPI service (port **8083**) mirroring the
established service conventions (config/logging/middleware/DI/Dockerfile as in the stub & ingestor).

### 1. The five contracts as first-class models (`app/models/`)

Each contract in `amendia_platform_contracts_v1.md` is implemented as a faithful Pydantic v2 model
(`extra="forbid"` ≡ `additionalProperties:false`; `Literal`/`Enum` for closed sets):

| # | Contract | Module |
|---|---|---|
| 1 | ProcessPack manifest | `process_pack.py` |
| 2 | Capability descriptor | `capability.py` |
| 3 | Artifact schema registration | `artifact_schema.py` |
| 4 | Dispatch event + accepted/rejected replies | `dispatch.py` |
| 5 | HITL task / approval model (+ thin HITL events) | `hitl_task.py` |
| — | Process instance (runtime-owned aggregate, not in the contracts doc) | `process_instance.py` |

Key modelling decisions:
- **`VersionedRef`** (`common.py`) is a value object parsing `<id>@<range-or-pin>` with `.ref_id` /
  `.spec` / `.is_pinned`, prefix-checked subclasses `CapabilityRef` / `ArtifactRef`, and clean
  string (de)serialization. Manifests/capabilities use these types, never raw strings.
- **Discriminated unions** for every `oneOf`: binding `executor` (capability|human), capability
  `runtime` (skill|mcp|llm), and a recursive **triage `predicate`** (all/any/not/leaf, leaf ops as an
  enum).
- **Self-contained invariants** are enforced in the models: hitl `role` required unless mode `none`;
  capability `runtime.kind == kind`; a `decided` HITL task requires a `decision` whose value is in
  `allowed_decisions`; `dispatch_rejected` requires a `reason`. **Cross-document** checks
  (capability-exists, schema-compat, BPMN parse) are explicitly *out of scope* and marked
  `# registry-validation` where they belong.
- **Events** share an `EventBase` and build routing keys **only** via `amendia_common.events.rk`. This
  slice added `Service.INGESTOR` / `Service.AGENT_RUNTIME` and the dispatch/HITL event-name constants
  to the shared lib (backward-compatibly).

### 2. Persistence (`app/db`, `app/dal`)

MongoDB `amendia`; one async repository per aggregate (no business logic); **natural keys** (not
Mongo ObjectIds) in the API. Unique indexes make versions immutable and a duplicate insert surfaces
as HTTP **409**.

| Collection | Unique key | Extra indexes |
|---|---|---|
| `process_packs` | (`pack_key`, `version`) | `status` |
| `capabilities` | (`capability_id`, `version`) | `status`, `kind` |
| `artifact_schemas` | (`artifact_key`, `version`) | `status` |
| `process_instances` | `process_instance_id`, `idempotency_key` | `exception_id` |
| `hitl_tasks` | `task_id` | (`status`, `role`), `process_instance_id` |
| `dispatch_log` | `event_id` | `exception_id` |

### 3. Seed dataset (`seed/wire-repair-standard/`)

A complete, mutually-consistent pack: the manifest with **all 12 bound elements** (+ the
`Gateway_Repairable` gateway variable, SoD policies), the verbatim BPMN, **10 capability descriptors**,
**7 artifact schemas** (draft 2020-12, `$id` per convention, `additionalProperties:false`), and the
reference AC01 exception envelope. Every binding capability is declared in `requires_capabilities`,
every IO schema in `artifacts`, and the gateway field (`repair_verdict`) is `required` in its schema.

### 4. Seeding (`app/seeding`)

An idempotent loader: validate every file through the models → meta-validate each embedded
`json_schema` (jsonschema draft 2020-12) → compute `bpmn_sha256` from the actual BPMN and inject it →
upsert by natural key. Re-running is a no-op; changing content for an existing (immutable) version is
refused. Exposed as CLI (`python -m app.seeding.load`), `POST /admin/seed` (guarded by
`AGENTRT_ENABLE_SEED_API`), and optional startup auto-seed (`AGENTRT_SEED_ON_STARTUP`, **true** in compose).

### 5. Read/inspection API (port 8083)

`GET /packs`, `/packs/{key}`, `/packs/{key}/{version}`, `/packs/{key}/{version}/bpmn` (`application/xml`);
`GET /capabilities[/{id}[/{version}]]`; `GET /artifact-schemas[/{key}/{version}]`; `GET /instances[/{id}]`;
`GET /hitl-tasks[/{id}]` (empty until execution); `POST /admin/seed`; `GET /health`. **No authoring
(create/update) APIs** — pack/capability/schema authoring belongs to the process-registry service later;
here they arrive only via seeding.

## Consequences

- The contract vocabulary is now enforced and stored, and a real pack (`wire-repair-standard@1.0.0`)
  is queryable — the substrate the execution slice, the process-registry, and the UI all build on.
- Versions are immutable by construction (unique keys + loader refusal), giving safe, repeatable seeds.
- **Explicitly deferred (not built here):** LangGraph execution/checkpointing, BPMN
  parsing/compilation, dispatch event consumers, HITL decision/resume APIs, cross-document registry
  validation, and any authoring flows. The dispatch/HITL models and the `process_instances` /
  `dispatch_log` / `hitl_tasks` collections exist now so those steps slot in without schema churn.
- **Deploy note:** the service declares the shared lib via a repo-relative path
  (`amendia-common = { path = "../../../libs" }`); `uv` rejects that path in a flattened image, so the
  Dockerfile preserves the repo layout under `/src` (as ADR-008 established) and sets `AGENTRT_SEED_DIR`
  explicitly (the installed package can't resolve the seed dir via `__file__`).
- **Open question narrowed:** the contracts assume the runtime interprets BPMN with LangGraph driving
  execution (bindings/HITL live in the manifest, not the XML) rather than embedding an external BPMN
  engine — but the execution engine choice remains open until the execution slice.
