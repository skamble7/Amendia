# Roles & Authorization — FAQ

Grounded in the code and docs (auth architecture, admin guide, persona map, platform contracts,
ADR-012/013/014). Read-only synthesis — see the cited files for the source of truth.

---

## Q: Is Amendia's RBAC a fixed set of platform-level roles (analyst, approver, process owner, admin), or can new roles / permissions be defined at the process-pack level?

**Bottom line:** Role **IDs** are extensible (free-form `role.*` strings, not a closed enum), but there is
**no pack-level permission model**, and packs can only **reference** roles — they cannot **define** or
**assign** them. Only two roles are truly platform-fixed as static guards; `ops_analyst`/`ops_approver` are
effectively pack/domain roles enforced dynamically. User↔role assignment is central (identity service).

### Roles are free-form `role.*` strings, not a closed set

The only constraint anywhere is a **shape regex**, never an enum or catalog:

```python
# libs/amendia_contracts/amendia_contracts/common.py
ROLE_ID_RE = r"^role\.[a-z0-9_.]+$"
RoleId = Annotated[str, StringConstraints(pattern=ROLE_ID_RE)]
```

- `amendia_auth` stores roles as a plain `Set[str]`; `require_roles(*roles)` is just an `in` membership
  check (`libs/amendia_auth/amendia_auth/dependencies.py`). Any `role.*` string works.
- The identity service assigns roles with **no allow-list / catalog check** — `role_repo.assign()` inserts
  whatever role id it is given; there is **no "role definitions" collection**, only user grants
  (`backend/services/platform/identity/app/dal/role_repo.py`). Grep for `ROLE_CATALOG` / `ALLOWED_ROLES` /
  `VALID_ROLES` across `libs/` and `backend/` returns zero hits.
- The "four roles" are a **convention**, not a fixed set. Only `role.platform.admin` and `role.process.owner`
  are code-fixed (static guards); `ops_analyst` / `ops_approver` are just the roles the **seeded** pack
  happens to reference. Since **ADR-026**, the admin role picker is **dynamic** — it lists roles *derived from
  active packs' bindings* via the registry's `GET /roles` endpoint (plus the two code-fixed platform roles
  merged in on the frontend, plus a validated custom-role free-text field). It is no longer a hardcoded
  frontend list — the old `ASSIGNABLE_ROLES` constant is retired.

### Only two roles are truly "platform-fixed"; analyst/approver are pack-domain roles

| Role id | How enforced |
|---|---|
| `role.platform.admin` | **Static guard** — identity admin/pending routers (`require_roles("role.platform.admin")`) + last-admin/self guardrails. |
| `role.process.owner` | **Static guard** — every process-registry mutation, incl. the onboarding wizard (`capabilities.py`, `packs.py`, `artifact_schemas.py`, `onboarding.py`). |
| `role.payments.ops_analyst` | **Dynamic** — never in a `require_roles` guard; matched at HITL claim/decide time. |
| `role.payments.ops_approver` | **Dynamic** — same. |

`ops_analyst` / `ops_approver` appear only in the payments **process-pack manifest** (as `hitl.role` /
`executor.role`) and are enforced dynamically by the runtime:

```python
# backend/services/agent-runtime/app/services/hitl_service.py
if task.role not in actor_roles:
    raise HitlError(403, ...)   # task.role comes from the pack binding's hitl.role
```

The `role.<domain>.<name>` namespace (`payments` = the domain/pack) shows these are **domain/pack roles**,
not platform-fixed ones. The platform only fixes `role.platform.admin` and `role.process.owner` as static
guards.

### Packs can *reference* new role IDs (pack-local) — but not *define* or *assign* them

- `ProcessPackManifest` (`libs/amendia_contracts/amendia_contracts/process_pack.py`) has **no role-catalog
  field**. Roles appear only as `RoleId` references inside `HumanExecutor.role` and `Hitl.role`. The validator
  only checks that a role is *present* when the HITL mode requires one — never against a central catalog.
- The registry explicitly models pack roles as **pack-local, derived from references**
  (`backend/services/process-registry/app/services/onboarding.py`):

  ```python
  # Roles are pack-local: the declared set plus any role referenced by a binding.
  declared = set(req.roles)
  for b in s.bindings:
      if b.hitl_role: declared.add(b.hitl_role)
      if b.executor_type == "human" and b.role: declared.add(b.role)
  s.roles = sorted(declared)
  ```

- **This derived set is now surfaced to admins (ADR-026).** `GET /roles` on the registry walks every *active*
  pack's bindings and returns `RoleInUse{role_id, label?, description?, sources[]}`; the admin picker builds its
  assignable list from it. So a pack that references `role.lending.underwriter` makes that role **appear in the
  picker automatically** once the pack is active — no code change. An optional per-pack `pack_roles` sidecar
  (authored on the onboarding **Policies** step: a label + description per role) only *enriches* those derived
  ids with human-facing names; ids are always derived from bindings, so seed/API-onboarded packs (no sidecar)
  surface correctly too, with a humanized fallback label.
- **Caveat:** a pack introducing `role.lending.underwriter` will work as a HITL gate — but only after a
  **platform admin separately grants** that role to users in the identity service. The pack emits role-id
  strings and makes them *grantable in the UI*; it does not, by itself, make anyone able to claim those tasks.

### Assignment is central; there is no permissions layer

- User↔role assignment is owned by the **identity service** (`role_assignments` collection; admin
  `POST`/`DELETE /users/{id}/roles`, plus email-staged pending grants). Packs never assign roles to users.
- **No permissions / scopes / entitlements / policy engine exist.** Authorization is purely role-membership
  (`require_roles(...)` static guards + the single dynamic `task.role ∈ actor_roles` HITL check). The only
  thing beyond RBAC is **Separation of Duties**, computed per-instance from *who actually acted* (by
  `amendia_user_id`), not from roles.

### Practical takeaway

- ✅ You can introduce **new pack/domain role IDs** freely (they gate HITL tasks); once the pack is active they
  **appear in the admin role picker automatically** (ADR-026), so an admin can grant them without a raw API
  call.
- ✅ You can **name** a pack-local role (label + description) on the onboarding Policies step — persisted in the
  `pack_roles` registry sidecar, shown in the picker. It's metadata only; the runtime never reads it.
- ❌ There is **no pack-level permission granularity** — only whole-role gating.
- ❌ Packs still cannot **assign** roles to users — that's a central admin operation (identity service). A pack
  contributes role *ids* (and optional names); a human still decides who holds them.
- 🔧 True pack-scoped roles or fine-grained abilities (a role meaningful only within one pack, or per-ability
  permissions) would be **new design** — today it is flat, global `role.*` RBAC.

### Sources

- `libs/amendia_contracts/amendia_contracts/common.py` (`ROLE_ID_RE`, `RoleId`)
- `libs/amendia_auth/amendia_auth/{models.py,dependencies.py}` (`roles: Set[str]`, `require_roles`)
- `backend/services/platform/identity/app/{routers/admin.py,dal/role_repo.py,seeding/seed.py}`
- `backend/services/process-registry/app/services/onboarding.py`, `app/validation/pack_validator.py`
- `backend/services/agent-runtime/app/services/hitl_service.py`
- `libs/amendia_contracts/amendia_contracts/process_pack.py`
- `backend/services/process-registry/app/{services/roles.py,routers/roles.py}` (the `GET /roles` derivation),
  `.../app/dal/pack_repo.py` (`pack_roles` sidecar)
- `webui/src/lib/roles.ts` (`buildAssignableRoles` — dynamic, not a hardcoded list),
  `webui/src/features/admin/RolePicker.tsx` (the master-detail picker)
- Docs: `amendia_auth_architecture.md`, `amendia_admin_user_management_guide.md`, `amendia_persona_map.md`,
  `amendia_platform_contracts_v1.md` (§0); ADR-012 / ADR-013 / ADR-014 / **ADR-025** (Policies-step authoring)
  / **ADR-026** (dynamic assignable roles + per-pack role registry).
