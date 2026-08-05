# CC Prompt — ADR-058 Phase E: frontend — upgrade the per-instance view (compose agent-runtime + glea-service)

**Read first:** `backend/docs/adr/ADR-058-glea-observability-on-otel-and-clickhouse.md` (the frontend section), the implementation plan, and the Phase A–D prompts. Phases A–D are landed: traces + lineage in ClickHouse, `glea-service` with `audit_events` + governed publishers + native egress (B), rationale + decision-trail + lineage read-models (C), and the aggregate metrics bundle (D). **Phase E is the frontend** — it turns the existing instance view into the real thing by composing two sources: **agent-runtime** for live state + artifact *values* (as today) and **`glea-service`** for the GLEA read-models. **Out of scope:** the cross-instance Governance & Audit console; the bundled Phase B fast-follow (config-forge publisher + hash-chain sealing); Phase D §3 alerting.

## The composition (ADR-058 §6)

`webui/src/features/instances/InstanceDetailPage.tsx` already renders the core view from agent-runtime (`:8083` instance detail: step tracker, actor log, artifacts incl. the Repair-Draft/Repair-Approved cards, checkpoints). Phase E keeps that and **adds** the GLEA sections fed by `glea-service`. The two sources compose: glea read-models return **references + metadata**; agent-runtime supplies the concrete **artifact values** the frontend diffs and renders.

## Scope

### 1. Wire `glea-service` into the webui API layer

Mirror the existing per-service pattern (`api/config.ts`, `api/client.ts`, `api/services/*`, `api/gen/*`, `features/instances/queries.ts`):
- Add a `glea` base to `api/config.ts` (`VITE_GLEA_BASE ?? "/api/glea"`) and the proxy mapping in **both** the Vite dev proxy and the built-image nginx config (→ `glea-service`), same as runtime/registry.
- Add `api/services/glea.ts` + `api/gen/glea.ts` types for the read-model endpoints: `GET /audit/instances/{cid}` (audit events, Phase B), `…/decision-trail`, `…/lineage`, `…/metrics` (C/D), and the small trace endpoint from §6.
- Add react-query hooks in `features/instances/queries.ts`.

### 2. Decision trail (reuse `CorrectionDiff`)

A new section on the instance page: per gate, the **proposed → approved delta** rendered with the existing `components/artifact/CorrectionDiff.tsx`. Fetch the decision-trail from glea (element_id, decided_by, role, decided_at, decision, sod_satisfied, comment, proposed/approved artifact refs); fetch the concrete proposed/approved artifact **values** from agent-runtime's instance artifacts (matched by the refs' `artifact_key`) and diff them. Show approver **name + role + timestamp + comment** and a **"Four-eyes ✓" badge** when `sod_satisfied` is true. This formalizes what the Repair-Draft/Repair-Approved cards hint at today.

### 3. Actor-log enrichment

Extend the existing actor-log list: show the **role** for human entries, render the **rationale** (from the actor-log entry meta / `amendia.rationale`, Phase C) where present (and nothing when absent), and a **"View trace"** affordance that focuses/links the corresponding span in the trace view (§6).

### 4. Lineage graph

Render the artifact **dataflow DAG** from glea `…/lineage` (nodes = artifacts with key/schema_ref/producer/authored_by_human; edges = producer→consumer; MI fan-in visible). **Keep dependencies minimal** — prefer a lightweight custom SVG/layered render (topological columns + SVG edges) over a heavy graph library; if a layout helper is genuinely needed, a small one (e.g. dagre) is acceptable but **flag the new dependency for review**. No `react-flow`-scale addition without sign-off.

### 5. Per-instance audit events + honest checkpoints

Render the append-only audit events for the instance (glea `GET /audit/instances/{cid}`), and make the existing **"Checkpoints — N recorded transitions"** line reference the **real audit rows** rather than an engine-internal count.

### 6. Trace view (one small backend read-model + the in-view render)

The ADR calls for the span tree rendered **in-view** from the trace read-model. Add a thin glea endpoint `GET /audit/instances/{correlation_id}/trace` → the instance's spans from `otel_traces` (span_id, parent_span_id, name, start, duration, the `amendia.*` attrs), and render an **in-view execution waterfall / indented tree** (no external trace UI, no heavy lib — an indented list with duration bars is enough). This is the only backend addition in Phase E; it reads `otel_traces` only, same pattern as the lineage read-model.

### 7. Aggregate tiles

Render the Phase D per-instance metrics bundle (`…/metrics`) as tiles on the instance view: approval-latency p50/p95, capability-exec-duration p50/p95, four-eyes-enforced, egress-denied, SLA breaches, HITL decisions by decision+role. Match the existing card/tile styling.

## Constraints (hard)

- **`glea-service` is optional at the UI layer.** If glea is unreachable or returns nothing (telemetry/audit not deployed, or an old instance with no data), the page **still renders the core agent-runtime view** (step tracker, actor log, artifacts); each GLEA section degrades to a graceful "unavailable / no data" state — **never a blank page or a crash.** Mirror the existing `isConnectivityError` handling.
- **Reuse existing components + design system:** `CorrectionDiff`, the artifact renderers, the card/tile styling. New sections must look native to the current page, not bolted on.
- **Minimal new dependencies:** prefer no-dep/lightweight rendering for the DAG and the trace waterfall; any new dep is flagged for review.
- **Domain-neutral:** product labels only; the read-models are already domain-neutral — do not hard-code pack/domain terms in the UI.
- Out of scope: cross-instance console, the bundled fast-follow, Phase D §3 alerting.

## Acceptance / exit criteria

1. The instance detail page composes agent-runtime + glea and renders all six additions: **decision trail** (proposed→approved via `CorrectionDiff` + name/role/timestamp/comment + Four-eyes badge), **actor-log** with role + rationale + View-trace, **lineage DAG** (incl. MI fan-in), **in-view trace tree**, **per-instance audit events** (+ honest checkpoints line), and the **metrics tiles**.
2. **glea-down resilience:** with `glea-service` unreachable, the page still renders the core agent-runtime view; every GLEA section shows a graceful unavailable/no-data state (no crash, no blank screen). Asserted in a component test.
3. `glea` is wired through the api layer: `config.ts` base, dev **and** built-image proxy, `services/glea.ts` + gen types, query hooks.
4. Matches the existing design system; `webui` typechecks, lints, and builds; existing tests pass; new component tests cover the decision-trail, lineage, tiles, and the glea-down fallback.
5. Against a live stack (end-of-track e2e), the wire-repair instance shows the real decision trail, lineage (with the MI fan-in where present), rationale, trace tree, audit events, and tiles.

## Working agreement

Supervised: you (CC) write the code; **propose up front** (a) the glea api-layer wiring, (b) the component breakdown for the new sections + how the decision-trail composes glea refs with agent-runtime artifact values, and (c) the DAG/trace-tree rendering approach + any new dependency, before large edits. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`). Do **not** run the full-stack e2e — single end-of-track gate after all phases.
