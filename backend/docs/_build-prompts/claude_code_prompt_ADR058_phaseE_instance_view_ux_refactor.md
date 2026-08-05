# CC Prompt — Phase E UX refactor: restructure the instance view (approved mockup)

**Read first:** the Phase E prompt (`claude_code_prompt_ADR058_phaseE_frontend_instance_view.md`). Phase E wired all the GLEA sections into `webui/src/features/instances/InstanceDetailPage.tsx`, and the end-to-end run confirmed they populate (after the glea concurrency fix). But the page is one ~6000px stacked column — cluttered. The operator has **approved a redesign mockup**, saved at `backend/docs/design/amendia_instance_view_mockup.html` — open it in a browser as the visual/IA target.

**This is a presentation / information-architecture refactor only.** Do **not** change data fetching, the two-source composition (agent-runtime live state + glea read-models), the glea read-model shapes, or the graceful-degradation behavior. Reuse the existing components and the webui's design tokens. **The mockup is the layout/IA reference only — do NOT copy its ad-hoc CSS or hardcoded colors; build with the app's own design system.**

## Target IA (the approved mockup)

Replace the single stacked column with: **summary header → KPI strip → four tabs**.

### 1. Summary header
Instance id (mono), and a subtitle line: `pack@version · correlation <id> · N steps · <duration>`. Status pills on the right: the outcome (e.g. `End_ServedPaid`) + `Completed`/`Failed`/`Running`. All from the agent-runtime instance state (as today).

### 2. KPI strip (stat tiles, directly under the header, always visible)
Adapt `MetricsTiles` into a compact 6-tile row: **Duration** (from instance-state start→end — **always shown**), **Approval latency** (p50/p95), **Capability exec p95**, **Four-eyes** count, **Egress-denied** count, **SLA breaches**. The last five come from the glea `…/metrics` bundle. If glea metrics is null/unavailable, those five degrade to `—`/"unavailable" **but Duration still renders and the page is fine.** Status colors **reserved** — green for the four-eyes ✓ / good counts, muted for zeros — from the existing token palette; no new colors, no per-metric rainbow.

### 3. Tabs — route the existing components into four tabs
Keep the current data hooks (`queries.ts`) and components; this is about **where** they render:
- **Overview** — the step tracker (existing, from instance state) + an **Activity feed** = the actor log (existing) enriched with **role** (from the decision-trail) and **rationale** (Phase C, where present), newest-first. Keep the honest "Checkpoints — N recorded transitions" line here (or in Artifacts).
- **Artifacts** — the instance artifacts as a **collapsible accordion, collapsed by default** (each row: artifact name + `schema_ref` + producer element; expand → the existing `ArtifactView`/renderers). Add an **Expand all / Collapse all** toggle. This is the main declutter.
- **Governance** — the existing **`DecisionTrail`** (proposed→approved via `CorrectionDiff`, decided-by + role + timestamp + comment + "Four-eyes ✓" badge) beside the existing **`AuditEvents`**.
- **Observability** — the existing **`LineageGraph`** + the in-view **trace tree/waterfall** + (optionally) a metrics detail view.

### 4. Graceful degradation preserved, per tab
Every GLEA-derived piece (the five glea KPI tiles, decision trail, audit, lineage, trace, rationale) keeps its glea-down "unavailable/no-data" state; the **core view** (header, step tracker, actor log, artifacts, Duration tile) always renders from agent-runtime. The glea-down component test must still pass, adapted to the tabbed layout.

## Constraints (hard)

- **Presentation-only:** no change to `queries.ts` hooks, `services/glea.ts`, the two-source composition, or the read-model shapes. New code is just the tab shell, the header, the KPI-strip adaptation, and the artifact accordion; everything else is the existing components relocated.
- **Use the webui's existing design tokens + components** (`DecisionTrail`, `AuditEvents`, `LineageGraph`, `MetricsTiles`, `ArtifactView`, `CorrectionDiff`, the trace tree, cards/badges). The mockup is IA reference only — do not import its CSS or hardcode its hex values. Domain-neutral labels.
- **No new dependencies.** Match the existing dark theme.
- **Accessible tabs** (keyboard + aria). Nice-to-have: reflect the active tab in a URL hash/query param so a link can deep-link a tab — skip if it complicates.

## Acceptance / exit criteria

1. The instance view renders as summary header + KPI strip + four tabs (Overview / Artifacts / Governance / Observability), matching the approved mockup's IA; artifacts collapsed by default with an Expand/Collapse-all toggle.
2. All Phase E content is still present and correct, just relocated into tabs; the decision-trail's glea-refs + runtime-values composition is unchanged.
3. glea-down: the five glea KPI tiles and the Governance/Observability GLEA sections degrade gracefully while the header, step tracker, actor log, artifacts, and the Duration tile still render. A component test asserts this against the tabbed layout.
4. `webui` typechecks, lints, and builds; existing tests pass; tests added/updated for tab switching, the artifact accordion default-collapsed state, and the glea-down per-tab fallback.

## Working agreement

Supervised: you (CC) write the code; **propose the component breakdown** (which existing components move to which tab; the new pieces — e.g. `InstanceHeader`, `KpiStrip`, `TabShell`, `ArtifactAccordion`) before large edits. The approved mockup is at `backend/docs/design/amendia_instance_view_mockup.html`. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`).
