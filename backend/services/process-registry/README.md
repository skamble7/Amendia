# Process Registry (v1)

The **authoring / write side** of the Amendia platform (Step 2 of the build plan). It stores and
validates the platform's contract declarations, runs the cross-contract **onboarding validator**,
drives the pack lifecycle with version pinning at activation, and answers the runtime triage lookup
(`POST /resolve`). No UI, no BPMN *execution* — validation only. Port **:8084**.

## Ownership split (registry writes, runtime reads)

The registry is the **write owner** of the three catalog collections — `capabilities`,
`artifact_schemas`, `process_packs` — plus its own `bpmn_documents` store. The **agent-runtime reads**
these same collections/shapes (contract models are shared via `libs/amendia_contracts`). Agent-runtime
keeps its own file-based seed path for now; it will be retired when the runtime switches to
registry-backed lookup (a later task). Contract models come from `amendia_contracts`; only
registry-local shapes (validation report, resolve I/O, activation `resolution`) live in this service.

No RabbitMQ in v1 — registry events (e.g. `pack_activated`) are deferred.

## Pack lifecycle

```
POST /packs (manifest)            → draft
PUT  .../bpmn  (application/xml)   → draft   (stores BPMN, sets process.bpmn_sha256; any re-upload → draft)
POST .../validate                 → validated  (all-clear) | draft (errors)   [report persisted]
POST .../activate                 → active   (only from validated; ranges pinned into resolved + resolution)
POST .../deprecate                → deprecated (only from active; removed from /resolve)
```
Versions are immutable — fix by new version. Multiple versions of one `pack_key` may be `active`
simultaneously; triage `priority` (then pack_key, then semver-desc) decides.

## The validator (7 stages)

1. **BPMN** — parse, one `process` with the manifest's `process_id`, sha256 match, supported element
   subset, one start, full reachability, exclusive/parallel gateway condition rules, no dangling flows.
2. **Bijection** — every service/user task ↔ exactly one binding; kind & executor-type consistency.
3. **Capabilities** — every ref resolves to an active registered version in range (unknown-id /
   no-version-in-range / only-deprecated distinguished; assist too).
4. **HITL & side-effect policy** — `side_effectful` ⇒ hitl ≥ `approve_actions`; binding ≥ capability
   `min_hitl_mode`; role present when mode ≠ none.
5. **Artifacts & IO** — refs resolve to non-deprecated schemas in range; binding IO reconciles with
   capability IO (name-set + overlapping ranges); input-produced-upstream (warning).
6. **Gateway variables** — each exclusive gateway declared; variable produced upstream; field
   `required` at every level in the resolved schema.
7. **Policies & triage** — SoD elements exist; triage rules parse; smoke-test each against the sample
   exception (info).

Findings are `{code, severity: error|warning|info, element_id?, path?, message}`; any error keeps the
pack out of `validated`. Report is deterministic and persisted (`GET .../validation-report`).

## Endpoints

```
POST /capabilities                       GET /capabilities[?status&kind]
GET  /capabilities/{id}                  GET /capabilities/{id}/{version}
POST /capabilities/{id}/{version}/deprecate

POST /artifact-schemas                   GET /artifact-schemas[?status]
GET  /artifact-schemas/{key}             GET /artifact-schemas/{key}/{version}
POST /artifact-schemas/{key}/{version}/deprecate

POST /packs                              PUT  /packs/{k}/{v}/bpmn   (application/xml)
POST /packs/{k}/{v}/validate             POST /packs/{k}/{v}/activate
POST /packs/{k}/{v}/deprecate
GET  /packs[?status&tenant_scope]        GET  /packs/{k}   GET /packs/{k}/{v}
GET  /packs/{k}/{v}/bpmn                 GET  /packs/{k}/{v}/validation-report
GET  /packs/{k}/{v}/resolution

POST /resolve   ({tenant, envelope})     GET /health
```

## Onboard a pack manually (dependency order)

```bash
# 1) register every artifact schema the pack references
curl -XPOST localhost:8084/artifact-schemas -H 'content-type: application/json' -d @art.payment.repair_verdict.json
# 2) register every capability
curl -XPOST localhost:8084/capabilities -H 'content-type: application/json' -d @cap.payment.sanctions_screen.json
# 3) submit the manifest (draft)
curl -XPOST localhost:8084/packs -H 'content-type: application/json' -d @manifest.json
# 4) upload the BPMN
curl -XPUT localhost:8084/packs/wire-repair-standard/1.0.0/bpmn -H 'content-type: application/xml' --data-binary @wire-repair.bpmn
# 5) validate, then 6) activate
curl -XPOST localhost:8084/packs/wire-repair-standard/1.0.0/validate | jq
curl -XPOST localhost:8084/packs/wire-repair-standard/1.0.0/activate | jq
# resolve an exception → pack pin + rule
curl -XPOST localhost:8084/resolve -H 'content-type: application/json' \
  -d '{"tenant":"bank-alpha","envelope": { ... normalized exception ... }}' | jq
```

The seed dataset is onboarded automatically through exactly this pipeline —
`python -m app.seeding.onboard_seed` (or `REGISTRY_SEED_ON_STARTUP=true`, set in compose).

## Run

```bash
cd backend/services/process-registry
uv pip install -e '.[dev]'
uvicorn app.main:app --port 8084 --reload
pytest
```

Tests use httpx `AsyncClient` + mongomock-motor with DI-overridden repositories (no live Mongo).
