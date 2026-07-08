# Agent Runtime (foundation)

This is the **foundation** slice of Amendia's agent-runtime service: the five platform
contracts as first-class Pydantic models, MongoDB persistence for them, an idempotent
seed loader, and a read/inspection API. It seeds the `wire-repair-standard` process pack.

**Not in this slice:** no LangGraph execution, no BPMN compilation, no event consumers /
dispatch handling, no HITL decision/resume APIs. Those are the next slice. There are also
**no authoring (create/update) APIs** for packs/capabilities/schemas — authoring belongs to
the process-registry service; here they arrive only via seeding.

**Ownership split (registry writes, runtime reads).** The `process-registry` service (:8084) is the
**write owner** of the `capabilities`, `artifact_schemas`, and `process_packs` collections — it runs
onboarding validation and pins versions at activation. The agent-runtime **reads** those same
collections. Both share the contract models, which now live in `libs/amendia_contracts` (the
`app/models/*` modules here are thin re-export shims). This service keeps its own file-based seed path
for now; it will be retired once the runtime reads registry-activated packs directly.

Source of truth for every model: [`backend/docs/amendia_platform_contracts_v1.md`](../../docs/amendia_platform_contracts_v1.md)
(shared implementation: `libs/amendia_contracts`).

## The five contracts (`app/models/`)

| # | Contract | Model module |
|---|---|---|
| 1 | ProcessPack manifest | `process_pack.py` |
| 2 | Capability descriptor | `capability.py` |
| 3 | Artifact schema registration | `artifact_schema.py` |
| 4 | Dispatch event + accepted/rejected replies | `dispatch.py` |
| 5 | HITL task / approval model (+ thin HITL events) | `hitl_task.py` |
| — | Process instance (runtime-owned aggregate) | `process_instance.py` |

Shared value types live in `common.py`: `VersionedRef` (`<id>@<range-or-pin>`, with
`CapabilityRef`/`ArtifactRef` prefix-checked subclasses), `HitlMode`, regex-backed id/pattern
string types, the `EventBase` whose `routing_key()` delegates to `amendia_common.events.rk`.

Models mirror their JSON Schemas exactly (`extra="forbid"` = `additionalProperties: false`),
use discriminated unions for `oneOf` (executor, capability runtime, triage predicate), and
enforce the self-contained cross-field invariants (hitl role required unless mode `none`;
`runtime.kind == kind`; decided task needs an allowed decision; etc.). Cross-**document**
checks (capability-exists, schema-compat, BPMN parse) are the registry's job later and are
marked `# registry-validation`.

## Persistence (`app/db`, `app/dal`)

MongoDB `amendia`; one repository per aggregate; natural keys (not ObjectIds) in the API.

| Collection | Unique key | Extra indexes |
|---|---|---|
| `process_packs` | (`pack_key`, `version`) | `status`, `tenant_scope` |
| `capabilities` | (`capability_id`, `version`) | `status`, `kind` |
| `artifact_schemas` | (`artifact_key`, `version`) | `status` |
| `process_instances` | `process_instance_id`, `idempotency_key` | (`tenant`, `exception_id`) |
| `hitl_tasks` | `task_id` | (`tenant`, `status`, `role`), `process_instance_id` |
| `dispatch_log` | `event_id` | (`tenant`, `exception_id`) |

A duplicate insert on a unique key surfaces as HTTP **409**. Versions are immutable.

## Seeding (`app/seeding`)

Reads `seed/wire-repair-standard/`, validates every file through the models, meta-validates
each artifact schema's embedded `json_schema` (draft 2020-12), computes `bpmn_sha256` from the
actual BPMN and injects it, then **upserts idempotently** by natural key. Re-running is a no-op;
changing content for an existing version is refused (409 / error) — versions are immutable.

Exposed two ways:
- CLI: `python -m app.seeding.load`
- API: `POST /admin/seed` (guarded by `AGENTRT_ENABLE_SEED_API`, default true; returns 404 when off)
- Optional auto-seed on startup: `AGENTRT_SEED_ON_STARTUP` (default false; **true** in compose)

## API (read/inspection only, port 8083)

```
GET /packs                          GET /capabilities
GET /packs/{pack_key}               GET /capabilities/{capability_id}
GET /packs/{pack_key}/{version}     GET /capabilities/{capability_id}/{version}
GET /packs/{pack_key}/{version}/bpmn   (application/xml)
GET /artifact-schemas               GET /instances        GET /instances/{id}
GET /artifact-schemas/{key}/{version}  GET /hitl-tasks     GET /hitl-tasks/{task_id}
POST /admin/seed                    GET /health
```

List endpoints support the indexed filters + `limit`/`offset`, newest-first.

## Run standalone

```bash
cd backend/services/agent-runtime
uv pip install -e '.[dev]'
cp .env.example .env            # adjust hosts if not using compose
uvicorn app.main:app --port 8083 --reload
python -m app.seeding.load      # or POST /admin/seed
```

## Run via docker-compose

```bash
docker compose -f backend/deploy/docker-compose.yml up --build   # comes up seeded
curl -s localhost:8083/packs/wire-repair-standard/1.0.0 | jq
curl -s localhost:8083/packs/wire-repair-standard/1.0.0/bpmn
```

## Tests

```bash
cd backend/services/agent-runtime
uv pip install -e '.[dev]'
pytest
```

Model round-trips, `VersionedRef` parsing, invariant enforcement, seed-loader idempotency/tamper
detection, repository 409s (mongomock-motor), and API tests (httpx `AsyncClient` with DI-overridden
repositories) — no live Mongo/Rabbit required.
