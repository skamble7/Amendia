# Claude Code prompt — ADR-060 UI follow-up: move Capabilities & Schemas from the global Registry to the pack level

A webui-only change completing **ADR-060** (`backend/docs/adr/ADR-060-pack-owned-capabilities-and-schemas.md`).
Now that capabilities and artifact schemas are **owned by a pack version** (no shared catalog), the global
Registry-level "Capabilities" and "Schemas" tabs no longer represent anything real — a capability/schema only
exists in the context of the pack that owns it. Move them to the pack detail view, scoped to that pack version.
No backend changes — ADR-060 already exposed the pack-scoped read routes and the registry OpenAPI client was
regenerated.

## Goal

- Registry landing page: **remove** the top-level `Capabilities` and `Schemas` tabs; keep `Processes` (the pack
  list). If `Processes` becomes the only tab, drop the tab bar and show the pack list directly.
- Pack detail page: **add** `Capabilities` and `Schemas` views showing **that pack version's owned** rows,
  fetched via the pack-scoped routes (`GET /packs/{pack_key}/{pack_version}/capabilities` and
  `.../artifact-schemas`) from the regenerated client.

## Read first

- `webui/src/features/registry/RegistryPage.tsx` — the global page + the `Processes | Capabilities | Schemas`
  tab bar to trim.
- `webui/src/features/registry/PackDetailPage.tsx` — the pack detail view; add the two owned-catalog views here
  (match its existing section/tab pattern).
- `webui/src/features/registry/queries.ts` — `useCapabilities` / schema hooks; today they hit the (now-gone)
  global catalog. Replace with **pack-scoped** hooks keyed by `(pack_key, pack_version)` using the regenerated
  client; remove or repoint the global ones.
- `webui/src/features/registry/SchemaTree.tsx` — reuse for rendering a schema if it already does.
- `webui/src/api/gen/registry.ts` — the regenerated client; use the pack-scoped list operations (do NOT
  hand-edit generated files; if a needed operation is missing, say so rather than inventing one).
- `webui/src/features/registry/registry.test.tsx` — update for the moved tabs.

## Tasks

1. **RegistryPage**: delete the `Capabilities` and `Schemas` tab entries and their panels/routes; keep
   `Processes`. Remove now-dead imports/hooks. If only one tab remains, render the pack list without a tab bar.
2. **PackDetailPage**: add `Capabilities` and `Schemas` sections/tabs (match the existing layout — it likely
   already tabs Overview/BPMN/etc.). Each lists the pack version's owned rows via the pack-scoped hook; reuse
   `SchemaTree` for schema rendering and the existing capability row/detail component if present. Empty/loading/
   error states consistent with the rest of the page.
3. **queries.ts**: introduce `usePackCapabilities(packKey, packVersion)` / `usePackSchemas(packKey, packVersion)`
   (names to match the file's convention) over the pack-scoped client operations; delete or repoint the global
   `useCapabilities`/schema hooks and any now-unused catalog query keys. Leave the onboarding wizard's own
   MCP-introspection Capabilities **step** untouched — that is a different, pre-commit flow.
4. **Tests/typecheck**: update `registry.test.tsx` (and any snapshot) for the relocated tabs; `tsc` clean.

## Do not

- No backend changes; no edits to generated API files.
- Do not touch the onboarding wizard's Capabilities step (pre-commit MCP introspection is unrelated).
- Do not add a pack **delete** action here — that is ADR-061 and lands on this same page separately.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- The global Registry page shows no Capabilities/Schemas tabs; a pack's detail page shows its **owned**
  capabilities and schemas, fetched pack-scoped, and two packs' views are independent.
- `npm run typecheck` and webui tests green; no dead imports/hooks/query keys left behind.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR060_ui_pack_scoped_catalog_report.md` (uncommitted):
(1) outcome one-liner; (2) files changed and what moved where; (3) the new pack-scoped hooks + which global
hooks/keys were removed; (4) verification — commands run (`tsc`, tests) and results, plus a note that a pack's
detail page renders its owned caps/schemas; (5) anything left open. Keep it to a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Stay inside `webui/` and the scope above.
