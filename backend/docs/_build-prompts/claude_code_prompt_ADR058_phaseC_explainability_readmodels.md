# CC Prompt — ADR-058 Phase C: explainability enrichment (agent rationale + decision-trail & lineage read-models)

**Read first:** `backend/docs/adr/ADR-058-glea-observability-on-otel-and-clickhouse.md`, the implementation plan, and the Phase A/B prompts + closeout. Phase A (traces + lineage in ClickHouse) and Phase B (`glea-service` + `audit_events` system-of-record + governed publishers + native egress) are landed and verified. **Phase C turns the substrate into explainability read-models** and captures agent rationale. It is mostly **read-side in `glea-service`** (pure ClickHouse reads over `otel_traces` + `audit_events`) plus a thin rationale-capture seam in `agent-runtime`. **Out of scope:** aggregate tiles/SQL endpoints (Phase D), frontend (Phase E), hash-chain sealing + config-forge publisher (the bundled Phase B fast-follow).

## Key boundary (unchanged): `glea-service` reads ClickHouse only

The read-models are built from what Phases A/B already persist — `otel_traces` (spans + span links + `amendia.*` attrs) and `audit_events` (governed rows). No new coupling to the engine or its checkpoint store. The frontend (Phase E) will compose these read-models with agent-runtime's live instance artifacts; Phase C delivers the **structure**, not the rendering.

## Scope

### 1. Agent-rationale capture (`agent-runtime` + `amendia_telemetry`)

Deep-agent/LLM capabilities reason before they answer; capture that reasoning as first-class explainability. Plain MCP tools have no rationale — **never fabricate one.**

- **Surface a bounded rationale from the executor result.** For the deep-agent/LLM executor (`executor/deep_agent.py`), expose the model's reasoning — the prose it emits alongside the structured output (see `_final_text`/`_parse_json`) — as a bounded `rationale` on the result (e.g. via `exec_meta["rationale"]` or a dedicated field). **Bound its length** (a sane cap, e.g. ~1–2 KB) so spans/logs don't grow unbounded. If the model emitted only structured output with no reasoning, rationale is absent.
- **Attach it** in `task_runner`: set the `amendia.rationale` span attribute (Phase A defined the key; populate it here) **and** record it into the node's `actor_log` entry meta, so it is both in the trace and in the checkpoint/actor-log surface. Optionally include the bounded rationale in the `ArtifactCommittedEvent` payload (Phase B) so the audit store carries it too — keep it bounded.
- **Domain-neutrality note:** the rule bars domain terms in structural **keys / attribute names / routing keys / columns** — not in **values**. `amendia.rationale` is a structural key; its value is model-produced content and may legitimately contain domain words (as `actor`, `schema_ref`, and artifact values already do). Do not scrub rationale values; just keep the key structural and the length bounded.

### 2. Decision-trail read-model (`glea-service`)

`GET /audit/instances/{correlation_id}/decision-trail` → the ordered list of HITL gate decisions for the run, built from `audit_events` (the enriched `HitlTaskDecided` rows + the surrounding `ArtifactCommitted` rows), correlated by `element_id` + `correlation_id`. Each entry returns:

- `element_id`, `decided_by`, `role`, `decided_at` (occurred_at), `decision`, `sod_satisfied`, `comment`;
- the **proposed** and **approved** artifact **references** — `artifact_key` + `schema_ref` for each side (the draft the agent produced vs. the human-authored output), so the frontend can fetch and diff the concrete values from agent-runtime in Phase E.

The read-model returns **references + metadata, not artifact payloads** — this keeps `glea-service` reading ClickHouse only and avoids putting artifact values (potentially large/sensitive) into the audit store. **If `comment` is not already on the decided audit row** (it exists in `hitl_service.decide` but may not have been carried onto the published event in Phase B), carry it now — it is small and non-sensitive. Ordered by `decided_at`.

### 3. Lineage projection API (`glea-service`)

`GET /audit/instances/{correlation_id}/lineage` → the artifact **dataflow graph** for the run, assembled from `otel_traces` (the Phase A span links **are** the lineage edges) enriched from `audit_events`:

- **Nodes** = artifacts: `artifact_key`, `schema_ref`, producer `element_id`, `authored_by_human`, `actor_kind`.
- **Edges** = producer → consumer: for each node span carrying `amendia.artifact_key`, its links point at the spans that produced its inputs; map span → its `amendia.artifact_key` to turn the span-link graph into an **artifact** DAG. Include the MI join fan-in (from the Phase A closeout: the aggregate links back to every per-iteration producer).

Pure ClickHouse read over `otel_traces` (+ `audit_events` for node metadata). No engine changes. Return a stable, renderable shape (nodes[] + edges[] with the fields above).

## Constraints (hard)

- **`glea-service` reads ClickHouse only** (`otel_traces` + `audit_events`); no engine / checkpoint coupling; it stays the read surface.
- **Domain-neutral keys/columns/attribute names** (values may contain content — see §1). Review gate.
- **Additive & side-effect-free** in agent-runtime: rationale capture must not change what any node computes, commits, or returns; absent rationale is normal (never a crash). Bound rationale length.
- Out of scope: aggregate tiles / SQL metric endpoints (Phase D), any frontend (Phase E), hash-chain sealing + config-forge publisher (bundled Phase B fast-follow), cross-instance console.

## Acceptance / exit criteria

1. In a full **wire-repair** run, the deep-agent/LLM capability node(s) carry a bounded `amendia.rationale` on their span **and** in the `actor_log` entry meta; plain MCP-tool nodes carry **no** rationale (no fabrication). Asserted in a test.
2. `GET /audit/instances/{correlation_id}/decision-trail` returns the gates in `decided_at` order, each with `decided_by` + `role` + `decision` + `sod_satisfied` + `comment` + the proposed/approved artifact references (`artifact_key`/`schema_ref`).
3. `GET /audit/instances/{correlation_id}/lineage` returns the artifact DAG (nodes + producer→consumer edges) that matches the Phase A span-link lineage for the run, **including the MI join fan-in** where the process uses multi-instance.
4. Both endpoints are **pure ClickHouse reads** (no agent-runtime change beyond rationale capture); domain-neutral keys; `glea-service` + `agent-runtime` unit suites green (integration e2e remains the end-of-track gate).

## Working agreement

Supervised: you (CC) write the code; **propose up front** (a) the rationale-capture seam (where the bounded rationale comes off the deep-agent result and how it's bounded), and (b) the two read-model query shapes (decision-trail and lineage response schemas + the ClickHouse queries), before large edits. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`). Do **not** run the full-stack e2e — single end-of-track gate after all phases.
