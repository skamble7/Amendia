# Amendia Build Plan — Registry & Runtime Sequence

The agreed sequence for building the process-registry and agent-runtime halves of the platform. Guiding principle: **contracts first, then both services in parallel** — the registry stores/validates declarations, the runtime interprets them; neither blocks the other once the contracts are fixed.

Reference: `amendia_platform_contracts_v1.md` (the five contracts). Current implemented state: stub_exception_generator (:8081) and ingestor (:8082) are live over the `amendia.events` topic exchange; ingestor lifecycle `received → dispatched → accepted/rejected` has only `received` wired — the remaining states are activated by Steps 2–3 below.

---

## Step 1 — Platform contracts (DONE, pending review hardening)

Define the five shared contracts:

1. **ProcessPack manifest** — versioned onboarding unit: BPMN ref + bindings (task → capability/role/HITL) + triage rules + declared capability & artifact dependencies + SoD policies. Ranges declare, activation pins.
2. **Capability descriptor** — independently registered, versioned capability (kind: skill | mcp | llm) with typed IO, side-effect classification, and `min_hitl_mode` floor. Enforces "capabilities built before process onboarding."
3. **Artifact schema registry conventions** — JSON Schema (2020-12) registration envelope, semver compatibility rules, runtime write-validation, gateway-variable requirements.
4. **Dispatch event** — `exception_dispatched` (ingestor → runtime) with pinned pack resolution + trace, and the `dispatch_accepted`/`dispatch_rejected` replies with idempotency on (tenant, exception_id, pack_key, pack_version).
5. **HITL task/approval model** — single work-item shape for all four human-touchpoint modes; SoD `excluded_users` resolved per instance at task creation; decision → graph resume mapping; immutable-after-decision audit semantics.

Exit criteria: contracts doc committed under `backend/docs/architecture/`; open questions logged (reject-semantics on review_after, partial action approval in v1, tenant-specific triage rules over shared packs).

## Step 2 — Process-registry service v1 (storage + validation)

Registry as CRUD + validation over the contracts — the onboarding *engine* without the onboarding *journey UI*:

- Collections + APIs for capability descriptors, artifact schema registrations, process packs (manifest + BPMN XML storage).
- The cross-contract onboarding validator (the validation matrix in the contracts doc): BPMN subset check, binding completeness/bijection, capability resolution within range, HITL floor & side-effect policy, artifact IO compatibility, gateway-variable satisfaction, SoD element existence.
- Pack lifecycle: `draft → validated → active → deprecated`; activation resolves ranges to pins.
- Derived runtime lookup: compiled triage-rule index across active packs, priority-ordered; `POST /resolve` (envelope in → pack pin + rule_id out) for the ingestor.

Exit criteria: `wire-repair-standard` can be onboarded via API from seed data and resolved from a sample wire exception envelope.

## Step 3 — Agent-runtime vertical slice

Execute `wire-repair-standard` end-to-end for one exception with at least one real HITL gate:

- Contract models live in the runtime as first-class citizens, persisted in MongoDB (groundwork prompt: `agent_runtime_models_prompt.md`).
- Consume `exception_dispatched`, reply accepted/rejected (activates ingestor's dormant states).
- BPMN + manifest → compiled LangGraph `StateGraph` (compile-don't-embed decision); Mongo checkpointer; process instance = checkpointed thread.
- Capabilities stubbed/simple for the slice (enrich, assess, draft_repair as skills or llm-kind; sanctions_screen as stub MCP).
- One real interrupt-based HITL gate (Task_ApproveRepair) with task creation, decision API, resume.
- Artifact writes validated against pinned schemas.

Exit criteria: generate exception via stub → ingest → resolve → dispatch → run → approve in an API call (UI later) → instance completes down the repair path; every state transition checkpointed.

## Step 4 — Full onboarding journey

Informed by what Steps 2–3 taught us:

- Onboarding UX (webui): upload BPMN, author bindings against registered capabilities, register artifact schemas, dry-run validation report, activate.
- Capability registration workflow incl. config-forge wiring (per-tenant capability config).
- Registry hardening: version diff/compatibility checks, deprecation flows, tenant-scoped rules (revisit the pack-owns-rules decision).
- HITL surfaces in webui: task inbox, review/approve screens rendered from artifact schemas, SoD-aware claiming.

Exit criteria: a second process pack (even a toy one) can be onboarded end-to-end without touching platform code.

---

## Parallelization note

After Step 1, Steps 2 and 3 proceed concurrently: the runtime slice can load seed pack data directly from files/Mongo before the registry's APIs exist, then switch to registry `resolve`/fetch once Step 2 lands. The seed folder (wire-repair pack + sample exception) is the shared fixture both steps develop against.
