# ADR-060 UI follow-up — pack-scoped Capabilities & Schemas: implementation report

## 1. Outcome

**Done.** The global Registry page no longer has `Capabilities`/`Schemas` tabs — it's now just the pack list. A
pack's detail page gains `Capabilities` and `Schemas` tabs that show **that pack version's OWNED** rows, fetched
pack-scoped. Webui-only; no backend or generated-file changes. `tsc` clean; webui tests green (27 files / 171,
+2 new).

## 2. Files changed / what moved where

- `src/features/registry/RegistryPage.tsx` — **removed** the `Processes | Capabilities | Schemas` tab bar and the
  `CapabilitiesCatalog`/`SchemasCatalog`/`CapabilityCard` panels; the page now renders `PacksCatalog` directly
  (no tab bar, since Processes was the only real tab). `StatusBadge` is still exported (PackDetailPage imports
  it). Dropped now-dead imports (`Tabs*`, `useState`, `ChevronDown`, `SchemaTree`, `SideEffectBadge`,
  `JsonSchema`, `CapabilityDescriptor`, `useCapabilities`, `useArtifactSchemas`).
- `src/features/registry/PackDetailPage.tsx` — **added** `Capabilities` and `Schemas` tabs (alongside
  Overview/Diagram/BPMN/Versions). New `PackCapabilities`/`PackSchemas` components list the pack version's owned
  rows with loading/empty/connectivity states matching the page; `CapabilityCard` (moved from RegistryPage)
  renders a capability, and `SchemaTree` renders each schema in an accordion (moved from RegistryPage).
- `src/features/registry/queries.ts` — see §3.
- `src/features/registry/registry.test.tsx` — added two tests (§4).

## 3. New pack-scoped hooks / removed globals

- **Added** `usePackCapabilities(packKey, packVersion)` and `usePackSchemas(packKey, packVersion)`, keyed
  `["pack-capabilities", packKey, packVersion]` / `["pack-schemas", …]`, each `enabled` only when both coords
  are present.
- **Fetching**: they call `listCapabilities({ pack_key, pack_version })` / `listArtifactSchemas({ pack_key,
  pack_version })` — the owned-rows browse **filtered to the pack's coords**. Note: the regenerated client has
  pack-scoped `/{capability_id}` and `/{capability_id}/{version}` operations but **no** pack-scoped *collection*
  operation (`GET /packs/{pk}/{pv}/capabilities` with no id) — so this uses the filtered list route, which the
  ADR-060 backend already scopes to the pack's owned rows (same result, no backend change, no generated-file
  edit). Query keys carry `(packKey, packVersion)`, so two packs' views are cached independently.
- **Removed** the dead global `useArtifactSchemas` (`["artifact-schemas-list"]`) — it was RegistryPage-only.
- **Kept** `useCapabilities` (the onboarding wizard's cross-pack reuse browse still uses it — the wizard's
  Capabilities step was left untouched per scope) and `useCapabilitySearch`. Left the pre-existing pack-scoped
  `useCapability`/`useArtifactSchemaVersions` in place.

## 4. Verification

- `npx tsc --noEmit` → **exit 0**.
- `npx vitest run` → **27 files / 171 tests passed** (was 169; +2).
- New tests in `registry.test.tsx`:
  - *"a pack's detail page shows its OWNED capabilities and schemas (fetched pack-scoped)"* — renders
    `/registry/packs/test-pack/1.0.0`, clicks the **Capabilities** tab (owned capability shows), asserts the
    fetch carried `pack_key=test-pack&pack_version=1.0.0` (proves pack-scoping / independence), then clicks
    **Schemas** (owned schema shows).
  - *"the global Registry page no longer has Capabilities/Schemas tabs"* — asserts neither tab exists on
    `/registry`.
- No dangling imports/hooks/keys: `rg` finds no `CapabilitiesCatalog`/`SchemasCatalog`/global `useArtifactSchemas`
  usage (the `useArtifactSchemas` name that remains is a **local** hook inside `ArtifactEditor.tsx`, unrelated).

## 5. Left open

- The pack-scoped **collection** fetch uses the filtered `GET /capabilities?pack_key&pack_version` route rather
  than a dedicated `GET /packs/{pk}/{pv}/capabilities` (which the OpenAPI client doesn't expose). If a reviewer
  prefers a true nested collection route for symmetry, that's a small **backend** addition (out of this
  webui-only scope) + a client regen — flagged, not invented here.
- ADR-061's pack **delete** action is intentionally not added (lands on this same PackDetailPage separately).
