# ADR-012 — Authentication & authorization backend: `amendia_auth`, identity service, Keycloak & enforcement

- **Status:** Accepted (auth §6 step 1 — backend)
- **Date:** 2026-07-08
- **Related:** `amendia_auth_architecture.md` (normative design — this ADR implements its §6 step 1);
  `amendia_platform_contracts_v1.md` (§0 `role.*` vocabulary); ADR-011 (agent-runtime execution — whose
  role-claim stub this removes), ADR-010 (process-registry), ADR-009 (agent-runtime foundation), ADR-007
  (stub), ADR-008 (ingestor); `backend/deploy/keycloak/README.md`.
- **Advances:** the "authn/z beyond the role-claim stub" item deferred by ADR-011; replaces the dev
  sign-in stub (three hardcoded users) as the platform's identity source.

## Context

Every service accepted callers unauthenticated: agent-runtime's `claim`/`decide` trusted a
`{user_id, role}` request body with a role-equality *stub* (ADR-011, `# TODO real authz`), and the webui
used a three-user dev switcher. Domain authorization (SoD exclusions, `allowed_decisions`, HITL floors)
was already Amendia-native and ran on Amendia user ids/roles — so what was missing was only *who the user
is*, proven, not *what they may do*.

The governing constraint from the design doc: **authenticate with the IdP, authorize in Amendia.** Trust
only `iss`/`sub` (+ email/name for display) from tokens; never build logic on vendor role/group claims
(`realm_access`, `groups`) — that is where IdP portability dies. Deployment model: **one deployment, one
customer, one issuer** — no multi-issuer/tenant mapping anywhere.

This ADR is the **backend** half; frontend PKCE is the next task. To avoid a broken main branch between
the two, a temporary compat bridge keeps the current webui working (Part E) — its removal is an explicit
step of the frontend task.

## Decision

### Part A — Keycloak dev IdP + committed realm (`:8087`)

`quay.io/keycloak/keycloak:26.0` in compose (`start-dev --import-realm`), realm export committed at
`backend/deploy/keycloak/amendia-dev-realm.json` (the reference for customer IdP integration):
public **PKCE-S256** client `amendia-webui` (webui redirect URIs, no secret, refresh rotation); a
dev-only confidential `amendia-dev-cli` with direct-access grants **isolated to it** (never on the SPA)
so curl can mint tokens; a **per-client `amendia-api` audience mapper** so every access token carries
`aud: amendia-api` (a custom client *scope* would replace Keycloak 26's built-in scopes and drop the
`sub` claim — the per-client mapper keeps `sub`/`email`/`profile` intact); users riya/marcus/priya (dev
passwords, emails/names); **deliberately zero
persona roles** — role assignments live in Amendia, proving the decoupling from day one.

### Part B — `libs/amendia_auth` (shared library)

Packaged like `amendia_contracts`/`amendia_bpmn` (deps: `pyjwt[crypto]`, `httpx`). Contents:
- **`TokenValidator`** — standard OIDC resource-server validation: discovery → JWKS, in-process TTL cache
  (10m) with a **single refresh on unknown `kid`** (rotation tolerance); **RS/ES family only** (`alg:none`
  and HS\* rejected → algorithm-confusion closed); exact `iss`, `aud` contains audience, `exp`/`nbf` with
  leeway. Yields `Principal(iss, sub, email?, name?, raw_claims)`; raises typed `AuthError(reason)`.
- **FastAPI dependencies** on a per-app `AuthContext` (`app.state.auth`): `current_principal` (401 +
  `WWW-Authenticate: Bearer`, `error="invalid_token"`, token never echoed); `current_user` → resolves the
  principal via the identity service into `AuthenticatedUser(amendia_user_id, roles, …)` with a short-TTL
  (30s) `(iss, sub)` cache and 403 `user_disabled`; `require_roles(*roles)` (403 naming the missing role);
  `principal_or_internal` and `require_internal` for the internal-token path (below).
- **Config** via `load_auth_settings("PREFIX_")` → `PREFIX_AUTH_ISSUER`/`_AUDIENCE`/`_JWKS_URI`/
  `_IDENTITY_BASE_URL`/`_INTERNAL_TOKEN`/`_COMPAT_STUB`/`_AUTH_DISABLED`. `auth_disabled` yields a
  synthetic all-roles user (tests/local only, loud warning; never a compose default).
- **Resolver seam:** the four services use the HTTP resolver; the identity service injects a **local**
  resolver so it never HTTP-calls itself. Claim-mapped roles are a documented extension point (interface
  only) behind the same seam.
- **22 tests** — validator against locally-generated RSA JWKS (valid / wrong iss / wrong aud / expired /
  unknown-kid→refresh / alg-confusion), dependency 401/403 shapes, cache TTL, disabled-user, compat.

### Part C — identity service (`backend/services/platform/identity`, `:8086`)

Mirrors the established service layout (`IDENTITY_` config, request-id middleware, health, Dockerfile).
Two aggregates (+ a seed sidecar): `users` `{amendia_user_id, identities:[{iss,sub}], email,
display_name, status}` (unique on `amendia_user_id` and multikey-unique on `(identities.iss, sub)`),
`role_assignments` (unique `(user, role)`, `role` validated against the contracts' `role.*` pattern), and
`pending_role_assignments` (by email). Endpoints:
- `POST /internal/resolve-principal` — **internal-token guarded**; looks up by `(iss, sub)`, **JIT-provisions**
  unknown identities (status from `IDENTITY_JIT_DEFAULT_STATUS`), writes back changed email/name. Called by
  `amendia_auth`'s `CurrentUser`.
- `GET /me` — bearer-authenticated *via the lib itself* (local resolver short-circuit); the webui's
  identity source next task.
- Admin (`require_roles("role.platform.admin")`): list/get users, assign/revoke roles (409 dup), disable/enable.

**Seeding strategy (chosen from the two the design allowed): role assignments keyed by email, materialised
on first login.** Seed writes `pending_role_assignments` (riya→`role.payments.ops_analyst`,
marcus→`role.payments.ops_approver`, priya→`role.process.owner`+`role.platform.admin`); JIT attaches them
to the new user on first resolve. This survives realm re-imports (no brittle Keycloak UUIDs) and needs no
admin-API call at seed time. Emails stay in lockstep with the realm export. **13 tests** (JIT/reconcile,
race recovery, admin guards, role CRUD, seed idempotency).

### Part D — enforcement + stub removal across the four services

Each service builds an `AuthContext` and applies guards at `include_router(dependencies=…)`:
- **Baseline:** every endpoint requires a principal except `/health`. Reads need only an authenticated
  principal (no role).
- **agent-runtime:** `claim`/`decide` take `CurrentUser`; **the `{user_id, role}` body fields and the
  role-equality stub are deleted** — identity and roles come from the token + identity service. The existing
  domain checks (task role ∈ the caller's roles, SoD by `amendia_user_id`, `allowed_decisions`, claim
  ownership) now run on `AuthenticatedUser`; `decided_by`/`assignee`/`actor_log` store `amendia_user_id`.
- **process-registry:** mutations (pack submit/BPMN/validate/activate/deprecate; capability & schema
  registration/deprecation) require `role.process.owner`. Reads stay principal-only.
- **stub:** `generate` principal-only.
- **Service-to-service** (ingestor→registry `/resolve`, runtime→registry reads, runtime/ingestor→stub
  fetch-back) carry a shared **`X-Amendia-Internal`** token, accepted via `principal_or_internal` on the
  reachable endpoints — one mechanism, one env-var convention, no weakening of user-facing routes.
- Every affected suite stays green (auth-disabled where auth isn't the subject) plus targeted per-service
  auth tests (401, 403 wrong-role, internal-token path). No service parses any vendor claim (grep-clean).

### Part E — temporary compat bridge (pre-PKCE webui)

> **Superseded:** the frontend PKCE task has landed, so this bridge and everything it touched
> (`*_AUTH_COMPAT_STUB` settings, the compat code paths, the compose flags, and the strict-override file)
> have been **removed** — the stack is strict by default. This section is retained as the historical record.

`*_AUTH_COMPAT_STUB=true` (compose default at the time): principal-only reads were exempt when no bearer was
present, and agent-runtime `claim`/`decide` accepted the legacy `{user_id, role}` body **only when no bearer
was present**. Every piece was tagged for removal by the frontend task. `docker-compose.auth-strict.yml`
flipped all four flags off → full enforcement (the state the frontend task lands in).

## Consequences

- **The dev sign-in stub is dead (backend).** Identity and roles are proven end-to-end: `tools/demo_wire_repair.sh`
  now mints real Keycloak bearers (riya=analyst, marcus=approver) and drives the wire-repair flow with **no
  role in the request body**; `decided_by` shows `usr-…` ids. With compat flags off the platform is fully
  enforced (401 unauthenticated, 403 on the wrong role/SoD); with them on (compose default) the current
  webui works unchanged.
- **IdP-portable by construction.** Two env values (issuer, SPA client id) + an audience swap the IdP; roles
  never come from the token, so Entra/Okta/Keycloak are interchangeable. Audit records already keyed by
  `amendia_user_id` survive an IdP migration (the `identities` array is re-keyable).
- **Dev-networking footgun recorded** (`AuthSettings.jwks_uri`): token `iss` is the browser-facing
  `http://localhost:8087/...` (unreachable inside compose), so services validate `iss` against it but fetch
  JWKS from the internal alias `http://keycloak:8080/.../certs`, bypassing discovery. This is the #1 setup
  gotcha; documented in the Keycloak README.
- **Deliberately deferred:** frontend PKCE + retiring the webui user-switcher (next task, which also removes
  the compat bridge); SCIM; the claim-mapped role strategy (interface reserved); mTLS/signed service tokens
  beyond the shared internal header (`TODO(auth-hardening)`); OPA/Cedar; admin UI; audit of role changes
  beyond `assigned_by/at`.
- **One non-obvious trap for maintainers:** `mongomock-motor` does not honour the multikey unique index on
  `identities`, so the JIT-race test drives the recovery path (insert → `DuplicateError` → re-fetch)
  directly; the real index enforces it. While it existed, the compat bridge was the *only* path that read a
  request-body identity; its removal tags listed everything the frontend task then deleted.

## Addendum — 2026-07-09

The identity admin surface was extended in **ADR-014** (pending-access CRUD, `role_details` on the admin
user views, and the self/last-admin guardrails). One note for API- and type-generation maintainers: those
guardrail failures — `self_protection`, `last_admin`, and the stage-access `user_exists` conflict — are
returned as `HTTPException(detail={"error": …})` dicts, which FastAPI does **not** model in its OpenAPI
`responses`, so `openapi-typescript` emits no type for them and the webui reads the `detail.error` codes
generically (in `features/admin/queries.ts`). This is deliberate; if a typed error contract is ever wanted,
add explicit `responses={409: …, 422: …}` models on the identity routers and regenerate (`pnpm gen:api`,
guarded by the new `pnpm gen:api:check`).
