# ADR-026 — Dynamic assignable roles: derive the admin role picker from active packs + a per-pack role registry

- **Status:** Accepted
- **Date:** 2026-07-15
- **Related:** **ADR-014** (Administration UI — the Assign-role (A3) / Stage-access (A4) dialogs this
  redesigns), **ADR-025** (onboarding `OnboardingSession` — the Policies step now authors role
  metadata), **ADR-012** (auth backend — `role.*` validated by pattern only, *no* central catalog;
  this builds directly on that premise), ADR-013 (auth frontend); `FAQ/Roles_FAQ.md` (the RBAC model),
  `amendia_services_reference.md` §4/§5, `amendia_persona_map.md`.
- **Supersedes:** the flat, hardcoded assignable-role list described in ADR-014 Part B.

## Context

Amendia roles are free-form `role.*` strings validated only by a shape regex (`ROLE_ID_RE`) — there is
**no role enum, catalog, or definitions collection** anywhere (ADR-012, `Roles_FAQ.md`). A pack freely
*references* role ids in its bindings (`hitl.role`, human `executor.role`); only two roles are code-fixed
by static route guards (`role.process.owner`, `role.platform.admin`).

But the admin **role picker** (the Assign-role and Stage-access dialogs, ADR-014) drove its options from a
**hardcoded four-role constant** (`ASSIGNABLE_ROLES` in `webui/src/lib/roles.ts`: analyst, approver,
process-owner, platform-admin). Consequence: a pack that invents `role.lending.underwriter` **could not be
granted through the product** — the picker didn't know it existed, and there was no roles-catalog endpoint
to tell it. The only path was a raw identity API call. As packs multiply, this gap widens and the fixed
list becomes actively misleading.

Two further problems surfaced with scale: a flat list of *every* role across *every* pack grows unbounded
(scroll fatigue, higher chance of mis-assignment), and derived role ids like `role.payments.ops_analyst`
carry no human-facing name unless the frontend happens to hardcode one.

## Decision

Make the assignable-role list **dynamic** — derived from what active packs actually reference — and give
each pack a **per-process role registry** so an operator can author a human label + description per role.

### Part A — `GET /roles`: roles in use, derived from active packs (process-registry)

A new read endpoint on the registry (the service that owns pack knowledge), returning
`RoleInUse{ role_id, label?, description?, sources[] }`:

- **Ids are derived, always.** `list_roles_in_use` walks every **active** pack (`pack_repo.list_active_raw`)
  and collects role ids from each binding's `hitl.role` and human `executor.role`. This is universal — it
  works for seed/API-onboarded packs that carry no authored metadata. `sources` is the list of
  `pack_key@version` packs that reference the id; results are deduped by `role_id`.
- **Metadata only enriches.** Each derived id is enriched with an optional per-pack `pack_roles` sidecar
  (Part B) for its `label`/`description` (first pack that has them wins). Absent metadata → `label`/
  `description` are `null` (the frontend supplies a fallback).
- **Baseline-guarded read.** Registered under the app-level `principal_or_internal` dependency — any
  authenticated principal may read it (a platform admin needs it to grant pack roles); it exposes **no
  mutation** and needs **no** `role.process.owner` gate. It deliberately does **not** surface the two
  code-fixed platform roles — those stay a small curated frontend constant merged in at the UI.

### Part B — the `pack_roles` sidecar + onboarding authoring

Role **metadata** is a UX/governance concern the runtime never reads, so it lives in a **registry-only
sidecar**, not in the immutable `ProcessPackManifest` (same pattern as `validation_reports` /
`pack_resolutions`):

- New collection **`pack_roles`** keyed `(pack_key, version)`; `pack_repo` gains
  `save_pack_roles` / `get_pack_roles` (an optional 4th collection — no-op when absent, back-compatible).
- The onboarding **Policies step** (ADR-025) gains optional `role_meta: {role_id → {label?, description?}}`
  on `SetPoliciesRequest`/`OnboardingSession`; `set_policies` keeps only metadata for a role that actually
  exists in the derived set. At **`commit`** (after activate) the session writes the sidecar:
  `save_pack_roles(pk, ver, [{role_id, label or humanize(role_id), description or ""} for role in s.roles])`.
- **No contract or identity-service change.** The manifest shape is untouched; the identity service still
  assigns any `role.*` and remains the assignment authority.

### Part C — the admin picker: dynamic + master-detail (webui)

- **`buildAssignableRoles(rolesInUse)`** merges the two code-fixed `PLATFORM_ROLES` (curated label/description)
  with the derived `GET /roles` rows, deduped by id. Label/description prefer the endpoint's authored value,
  then the curated platform map, then a **`humanizeRole`** fallback (last dotted segment, Title-Cased) — so a
  brand-new pack role is grantable with a sensible name even before anyone authors metadata. `ASSIGNABLE_ROLES`
  is **retired**.
- **Master-detail `RolePicker`** (shared by Assign single-select and Stage-access multi-select): packs on the
  left (a pinned **Platform** group, one entry per active pack labeled by title, a pinned **Custom role**
  entry), the selected group's roles on the right. Only one group's roles render at a time, so the list stays
  short regardless of pack count; per-pack selection-count badges keep multi-select picks visible; a pack
  filter appears once the rail grows. Roles the user already holds stay visible marked "granted" (their pack
  doesn't vanish).
- **Validated custom-role field** (in the Custom group) lets an admin grant a `role.*` a pack references
  **before it's active** — it moves into its pack's group automatically once the pack goes live.

## Consequences

- **A new pack's roles are grantable through the product automatically** once it's active — no raw API call,
  no frontend change. The picker is a live view of the platform's actual role surface.
- **Design invariant: ids derived, metadata enriches.** The authoritative role *set* always comes from active
  packs' bindings; the sidecar and the curated platform constant only attach names. This is why seed packs
  (no sidecar) still appear correctly — their ids are derived and named by the frontend fallback / curated map.
- **The two platform roles remain a curated frontend constant.** They are fixed by code guards, not the
  hardcoding the change removed; zeroing even those out would be a separate follow-up.
- **Scales in UX, not just data.** Master-detail bounds the visible role count per pack; the flat-list scroll
  fatigue that motivated the redesign is gone.
- **No new enforcement surface.** `GET /roles` is a read; authorization is unchanged (identity assigns,
  `require_roles` guards, the single dynamic HITL `task.role ∈ actor_roles` check). SoD is still per-instance
  from who acted.

## Traps recorded for maintainers

1. **`GET /roles` derives ids from bindings; the sidecar only names them.** Never treat `pack_roles` as the
   source of truth for *which* roles exist — a pack with no sidecar (every seeded/API-onboarded pack) must
   still surface its roles. If you refactor, keep derivation and enrichment separate.
2. **It returns only pack-referenced roles — the two platform roles are merged in at the frontend**
   (`PLATFORM_ROLES`), not by the endpoint. Don't "fix" the endpoint to include them; the split is deliberate
   (they're code-fixed, not pack-derived).
3. **Metadata is filtered to real roles at `set_policies`.** `role_meta` for an id not in the derived set is
   dropped, so authored labels can't outlive the role that justified them.
4. **The picker degrades gracefully.** If `GET /roles` (or the active-packs title lookup) fails, the dialog
   still shows the Platform group + Custom field. Keep that fallback — entitlement UI must never hard-fail.
5. **`humanizeRole` is a *fallback*, not a rename.** It only fills a blank label; authored metadata and the
   curated platform map always win. Don't route curated roles through it.
